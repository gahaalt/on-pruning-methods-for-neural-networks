import argparse
import os

import yaml
from tools.utils import get_date_from_exp


def recursive_collect_logs(path):
    logs = []
    for x in os.listdir(path):
        if x.endswith('.yaml'):
            full_path = os.path.join(path, x)
            with open(full_path, 'r') as f:
                for exp in yaml.safe_load_all(f):
                    if exp:
                        if exp not in logs:
                            logs.append(exp)
        if os.path.isdir(npath := os.path.join(path, x)):
            for exp in recursive_collect_logs(npath):
                if exp not in logs:
                    logs.append(exp)
    return logs


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Manipulation of .yaml logs.")
    parser.add_argument('-p', '--path', type=str, required=True,
                        help='directory from which recursive log gathering will begin')
    parser.add_argument('-d', '--dest', type=str, default=None,
                        help='where to save gathered yaml logs, by default it is the '
                             'same as --path')
    parser.add_argument('-s', '--sort-by', type=str, default='TIME',
                        help='which key from the dictionary to use to sort entries')
    parser.add_argument('--reverse', action="store_false")
    args = parser.parse_args()
    if args.dest is None:
        args.dest = os.path.join(args.path, 'gathered_logs.yaml')

    logs = recursive_collect_logs(args.path)

    if args.sort_by.lower() == 'time':
        logs = sorted(logs, key=lambda x: get_date_from_exp(x), reverse=parser.reverse)
    else:
        key = args.sort_by
        logs = sorted(logs, key=lambda x: x[key], reverse=parser.reverse)

    with open(args.dest, 'w') as f:
        yaml.safe_dump_all(logs, f)

datetime.datetime.strptime('2021.03.12 5:3', "%Y.%m.%d %H:%M")
