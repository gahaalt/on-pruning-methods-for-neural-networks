import os
import yaml
import argparse
import sys

parser = argparse.ArgumentParser(description="Manipulation of .yaml logs.")
parser.add_argument('--path', type=str,
                    help='directory from which recursive log gathering will begin')
parser.add_argument('--dest', type=str,
                    help='where to save gathered yaml logs')

args = parser.parse_args()


def recursive_gather_logs(path):
    logs = []
    for x in os.listdir(path):
        if x.endswith('.yaml'):
            full_path = os.path.join(path, x)
            with open(full_path, 'r') as f:
                for exp in yaml.safe_load_all(f):
                    if exp:
                        if not exp in logs:
                            logs.append(exp)
        if os.path.isdir(npath := os.path.join(path, x)):
            for exp in recursive_gather_logs(npath):
                if not exp in logs:
                    logs.append(exp)
    return logs


logs = recursive_gather_logs(args.path)
with open(args.dest, 'w') as f:
    yaml.safe_dump_all(logs, f)
