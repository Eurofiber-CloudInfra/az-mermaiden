#!/usr/bin/env python3
"""Handle graphing of Azure network deployments.

Copyright 2021 Alexander Kuemmel

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

__version__ = '0.1.0'
__author__ = 'Alexander Kuemmel <akisys@github>'
__license__ = 'Apache License 2.0'


import sys
assert sys.version_info >= (3, 7)

import json
import argparse
import shutil
import subprocess
import logging
import textwrap
import dataclasses
import zlib
from string import Template
from pathlib import Path
from contextlib import contextmanager
from collections import namedtuple
from pprint import pprint as pp

# mini semver setup
semver = namedtuple('semver', ['major', 'minor', 'patch'])

# mermaid templates and defaults
mmd_vnet_label = Template('$node{{"$label [p:$pc]"}}')
mmd_vnet_label_rnd = Template('$node("$label [p:$pc]")')
mmd_vnet_peering_wl = Template('$node ---|"$label"| $peer')
mmd_vnet_peering_nl = Template('$node --- $peer')
mmd_vnet_style = Template('style $node $style')
mmd_subgraph_begin = Template('subgraph "$label"')
mmd_subgraph_end = "end"
mmd_header_data = """
graph LR
"""
mmd_footer_data = """
"""
mmd_vnet_styles_by_peer_count = {
  range(0,1): "fill:#8cbed6",
  range(1,10): "fill:#f8de7e",
  range(10,20): "fill:#ff8243",
  range(20,50): "fill:#ff5349",
  range(50,255): "fill:#c90016",
}

# mini azure res setup
@dataclasses.dataclass
class az_res:
  id: str
  resourceGroup: str = None
  name: str = None
  hash: str = None

  def __post_init__(self):
    self.hash = str(zlib.adler32(self.id.encode('ascii')))

  def __str__(self) -> str:
    return self.hash

  def _fields() -> list:
    return [f.name for f in dataclasses.fields(__class__)]


@dataclasses.dataclass
class az_vnet(az_res):
  resourceGroup: str = None
  name: str = None
  sub_id: str = None
  peers: list = dataclasses.field(default_factory=list)

  def __post_init__(self):
    id_split = self.id.split('/')
    self.resourceGroup = id_split[4]
    self.name = id_split[8]
    self.sub_id = id_split[2]
    super().__post_init__()


@dataclasses.dataclass
class az_vnet_peering(az_res):
  thisVnet: az_vnet = None
  peeredVnet: az_vnet = None

  def __post_init__(self):
    super().__post_init__()
    self.hash = str(int(self.thisVnet.hash)+int(self.peeredVnet.hash))


@dataclasses.dataclass
class runtime_data:
  vnet_map: dict = dataclasses.field(default_factory=dict)
  peer_map: dict = dataclasses.field(default_factory=dict)
  subscription_data: list = dataclasses.field(default_factory=list)
  render_as_subgraph: bool = False
  render_with_edge_labels: bool = True


# logging setup
format = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(format=format, level=logging.DEBUG, datefmt="%H:%M:%S")

# requirements presets
azcmd = "az"
azver = semver._make("2.27.0".split('.'))



@contextmanager
def use_azure_account(sub_id: str):
  curr_sub_id = None
  try:
    logging.debug("Retrieving az default account")
    current_account = json.loads(subprocess.check_output("az account show".split(), shell=False))
    curr_sub_id = current_account.get('id')
    if current_account.get('isDefault') and curr_sub_id == sub_id:
      logging.debug(f"Skipping az account change, already active on correct subscription {curr_sub_id}")
    else:
      logging.debug(f"Changing az default account to subsription {sub_id}")
      subprocess.check_call(f"az account set --subscription {sub_id}".split(), shell=False)
      current_account = json.loads(subprocess.check_output("az account show".split(), shell=False))

    yield current_account

  finally:
    logging.debug(f"Resetting az default to account subscription {curr_sub_id}")
    subprocess.check_call(f"az account set --subscription {curr_sub_id}".split(), shell=False)


def check_local_requirements():
  if not shutil.which(azcmd):
    raise Exception(f"Could not find executable Azure CLI ({azcmd}) in $PATH")

  cmd_base = f"{azcmd} version".split()
  cmd_output = json.loads(subprocess.check_output(cmd_base, shell=False))
  az_check_ver = semver._make(cmd_output.get('azure-cli-core').split('.'))
  if not az_check_ver >= azver:
    raise Exception(f"Minimum version requirement for 'az' command not met, expecting at least {azver._asdict()}, but got {az_check_ver._asdict()}")


def get_az_vnet(data: dict) -> az_vnet:
  vnet_extract = {key: data.get(key) for key in data.keys() if key in az_vnet._fields()}
  return az_vnet(**vnet_extract)


def get_az_vnet_peers(data: dict) -> az_vnet_peering:
  azvnet = get_az_vnet(data)
  for raw_peering in data.get('virtualNetworkPeerings'):
    peered_vnet = get_az_vnet(raw_peering.get('remoteVirtualNetwork'))
    peering_extract = {key: raw_peering.get(key) for key in raw_peering.keys() if key in az_vnet_peering._fields()}
    peering = az_vnet_peering(**peering_extract, peeredVnet=peered_vnet, thisVnet=azvnet)
    yield peering


def get_mmd_vnet_style(peer_count: int = 0):
  logging.debug(f"Getting style for peer count {peer_count}")
  for r,v in mmd_vnet_styles_by_peer_count.items():
    if peer_count in r:
      return v
  return None


def render_data(runtime: runtime_data) -> str:
  output_buffer = []
  processed_vnet_refs = []
  for subdata in runtime.subscription_data:
    render_data = []
    subscription = subdata.get('subscription')
    vnet_refs = subdata.get('vnet_refs')

    if runtime.render_as_subgraph:
      render_data.append(mmd_subgraph_begin.substitute(label=subscription.get('name'))) 

    for node_hash in vnet_refs:
      node = runtime.vnet_map[node_hash]
      # render vnet's differently if they don't have any peers
      if len(node.peers) > 0:
        node_label = mmd_vnet_label
      else:
        node_label = mmd_vnet_label_rnd

      peer_count = len(node.peers)
      render_data.append(node_label.substitute(node=node.hash, label=node.name, pc=peer_count))
      render_data.append(mmd_vnet_style.substitute(node=node, style=get_mmd_vnet_style(peer_count)))

    if runtime.render_as_subgraph:
      render_data.append(mmd_subgraph_end)
    output_buffer.extend(render_data)

    processed_vnet_refs.extend(vnet_refs)
    pass

  # render all nodes not belonging to visited subscriptions
  unprocessed_vnet_refs = set(runtime.vnet_map.keys()).difference(processed_vnet_refs)
  if runtime.render_as_subgraph:
    output_buffer.append(mmd_subgraph_begin.substitute(label="__EXTERNAL__")) 
  for node_hash in unprocessed_vnet_refs:
    node = runtime.vnet_map[node_hash]
    peer_count = len(node.peers)
    node_label = mmd_vnet_label_rnd
    output_buffer.append(node_label.substitute(node=node, label=node.name, pc=peer_count))
    output_buffer.append(mmd_vnet_style.substitute(node=node, style=get_mmd_vnet_style(peer_count)))
  if runtime.render_as_subgraph:
    output_buffer.append(mmd_subgraph_end)

  # render all peering connections at last
  for peer in runtime.peer_map.values():
    if runtime.render_with_edge_labels:
      output_buffer.append(mmd_vnet_peering_wl.substitute(node=peer.thisVnet, label=peer.name, peer=peer.peeredVnet))
    else:
      output_buffer.append(mmd_vnet_peering_nl.substitute(node=peer.thisVnet, peer=peer.peeredVnet))

  return "{0}\n{1}\n{2}".format(mmd_header_data, '\n'.join(output_buffer), mmd_footer_data)


def aggregate_subscription(sub_id: str, runtime: runtime_data):
  data_map = {}
  sub_vnet_refs = []
  with use_azure_account(sub_id) as active_sub:
    cmd_base = "az network vnet list".split()
    cmd_output = json.loads(subprocess.check_output(cmd_base, shell=False))
    for raw_vnet in cmd_output:
      azvnet = get_az_vnet(raw_vnet)
      if azvnet.hash not in runtime.vnet_map:
        runtime.vnet_map[azvnet.hash] = azvnet

      for peer in get_az_vnet_peers(raw_vnet):
        runtime.vnet_map[azvnet.hash].peers.append(peer)

        if peer.peeredVnet.hash not in runtime.vnet_map:
          runtime.vnet_map[peer.peeredVnet.hash] = peer.peeredVnet
        # store peer also peered vnet object
        runtime.vnet_map[peer.peeredVnet.hash].peers.append(peer)

        if peer.hash not in runtime.peer_map:
          runtime.peer_map[peer.hash] = peer

      sub_vnet_refs.append(azvnet.hash)
    data_map.update(subscription=active_sub, vnet_refs=set(sub_vnet_refs))
  runtime.subscription_data.append(data_map)


if __name__ == "__main__":
  logo = '''
   __  __ (Iron)                    _     _            
  |  \/  | ___ _ __ _ __ ___   __ _(_) __| | ___ _ __  
  | |\/| |/ _ \ '__| '_ ` _ \ / _` | |/ _` |/ _ \ '_ \ 
  | |  | |  __/ |  | | | | | | (_| | | (_| |  __/ | | |
  |_|  |_|\___|_|  |_| |_| |_|\__,_|_|\__,_|\___|_| |_|
   by akisys                                           
  '''
  formatter = lambda prog:argparse.RawDescriptionHelpFormatter(prog,max_help_position=70)
  parser = argparse.ArgumentParser(description=textwrap.dedent(logo), formatter_class=formatter)
  parser.add_argument('-v', dest="verbosity", action="count", help="Stackable verbosity level indicator, e.g. -vv")
  subs_input_group = parser.add_mutually_exclusive_group()
  subs_input_group.add_argument('-s', dest="subs", action="append", help="Subscription to render out, can be used multiple times")
  subs_input_group.add_argument('-sf', dest="subs_file", type=argparse.FileType('r'), help="Subscriptions to render out, one ID per line")
  parser.add_argument('-o', dest="outfile", type=Path, required=True)
  parser.add_argument('-el', dest="render_edge_labels", action="store_true", default=False)
  parser.add_argument('-sg', dest="render_sub_graphs", action="store_true", default=False)

  try:
    args = parser.parse_args()
    # logging level setup
    logger = logging.getLogger()
    if not args.verbosity:
      logger.setLevel(logging.WARN)
    elif args.verbosity == 1:
      logger.setLevel(logging.INFO)
    elif args.verbosity >= 2:
      logger.setLevel(logging.DEBUG)

    check_local_requirements()

    runtime = runtime_data()
    sub_ids = args.subs or args.subs_file.readlines()
    sub_ids = [line.strip() for line in sub_ids if not line.startswith('#')]

    logging.info("Collecting data")
    for sub_id in sub_ids:
      logging.debug(f"Processing {sub_id}")
      aggregate_subscription(sub_id=sub_id, runtime=runtime)
    
    logging.info("Rendering data")
    runtime.render_with_edge_labels = args.render_edge_labels
    runtime.render_as_subgraph = args.render_sub_graphs
    output_text = render_data(runtime)

    logging.info("Writing output")
    with open(args.outfile, "w") as fp:
      fp.write(output_text)
    pass

  except Exception as ex:
    logging.fatal(ex)
    sys.exit(1)
