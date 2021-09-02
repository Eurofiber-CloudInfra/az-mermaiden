# az-mermaiden

Convert Azure Peering information into Mermaid diagram definitions.

## Requirements

- Python >= 3.7

## Usage

```
usage: mermaiden.py [-h] [-v] [-s SUBS | -sf SUBS_FILE] -o OUTFILE [-el] [-sg]

 __  __ (Iron)                    _     _            
|  \/  | ___ _ __ _ __ ___   __ _(_) __| | ___ _ __  
| |\/| |/ _ \ '__| '_ ` _ \ / _` | |/ _` |/ _ \ '_ \ 
| |  | |  __/ |  | | | | | | (_| | | (_| |  __/ | | |
|_|  |_|\___|_|  |_| |_| |_|\__,_|_|\__,_|\___|_| |_|
 by akisys                                           

optional arguments:
  -h, --help     show this help message and exit
  -v             Stackable verbosity level indicator, e.g. -vv
  -s SUBS        Subscription to render out, can be used multiple times
  -sf SUBS_FILE  Subscriptions to render out, one ID per line
  -o OUTFILE
  -el
  -sg

```
