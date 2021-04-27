import argparse
import datetime
import os

import yaml

import tools.constants as C
from tools.utils import get_cprint

cprint = get_cprint('green')


def recursive_collect_logs(path, verbose=False, level=0):
    logs = []
    for x in os.listdir(path):
        if x.endswith('.yaml'):
            full_path = os.path.join(path, x)
            with open(full_path, 'r') as f:
                for exp in yaml.safe_load_all(f):
                    if exp and exp not in logs:
                        logs.append(exp)
        if os.path.isdir(npath := os.path.join(path, x)):
            for exp in recursive_collect_logs(npath, verbose=verbose, level=level + 1):
                if exp not in logs:
                    logs.append(exp)
    if len(logs) and (verbose or level == 0):
        cprint(f"{'  ' * level}Found {len(logs):^5} logs under {path}")
    return logs


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="recursive gathering of .yaml logs.")
    parser.add_argument('path', type=str, default='.', nargs='*',
                        help='directory from which recursive log gathering will begin')
    parser.add_argument('--dest', type=str, default='yaml_logs',
                        help='directory of new .yaml file')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='print directories during recursive search')
    args = parser.parse_args()

    logs = []
    for path in args.path:
        log = recursive_collect_logs(path, verbose=args.verbose)
        logs.extend(log)

    os.makedirs(args.dest, exist_ok=True)
    now = datetime.datetime.now().strftime(C.time_formats[1])
    dest = os.path.join(args.dest, f'logs_{now}.yaml')
    with open(dest, 'w') as f:
        yaml.safe_dump_all(logs, f)
    cprint(f"SAVED: {dest}")
