import argparse
import importlib
import os
import sys
import time

import yaml

from tools import parser, utils

print = utils.get_cprint(color='red')

arg_parser = argparse.ArgumentParser(prefix_chars='-+')
arg_parser.add_argument("--dry",
                        action="store_true",
                        help="skip execution but parse experiments")
arg_parser.add_argument("--exp",
                        default='experiment.yaml',
                        type=str,
                        help="path to .yaml file with experiments")
arg_parser.add_argument("--pick",
                        "--cherrypick-experiments",
                        type=int,
                        nargs='*',
                        help="run only selected experiments, e.g. 0 1 3 or just 1")
args, unknown_args = arg_parser.parse_known_args()
print(f"UNKNOWN CMD ARGUMENTS: {unknown_args}")
print(f"  KNOWN CMD ARGUMENTS: {args.__dict__}")

parameters = utils.filter_argv(unknown_args, include=['+'], exclude=['-'])
for p in parameters:
    sys.argv.remove(p)  # filter out parameters, leave only real arguments

default_config, experiment_queue = parser.load_from_yaml(yaml_path=args.exp,
                                                         cmd_parameters=parameters)

for exp_idx, exp in enumerate(experiment_queue):
    assert isinstance(exp, utils.Experiment)

    if args.pick and exp_idx not in args.pick:
        print(f"SKIPPING EXPERIMENT {exp_idx} (not picked)")
        continue

    print()
    print(f"NEW EXPERIMENT {exp_idx}:\n{exp}")
    if args.dry:
        continue
    if exp.Name == "skip":
        print(f"SKIPPING EXPERIMENT {exp_idx} (Name == skip)")
        continue

    exp._reset_usage_counts(
        ignore_keys=[
            'REP', 'RND_IDX', 'HOST',
            'GlobalRepeat', 'GlobalQueue', 'Repeat', 'Name', 'Module', 'YamlLog'
        ])

    try:
        t0 = time.time()
        module = importlib.import_module(exp.Module)
        module.main(exp)  # RUN MODULE
        exp.TIME_ELAPSED = time.time() - t0

        if dirpath := os.path.dirname(exp.YamlLog):
            os.makedirs(dirpath, exist_ok=True)
        with open(f"{exp.YamlLog}", "a") as f:
            yaml.safe_dump(exp.todict(), stream=f, explicit_start=True, sort_keys=False)
        print(f"SAVED {exp['YamlLog']}")

    except KeyboardInterrupt:
        print(f"\n\nSKIPPING EXPERIMENT {exp_idx}, WAITING 2 SECONDS BEFORE "
              f"RESUMING...")
        time.sleep(2)

if isinstance(experiment_queue, parser.YamlExperimentQueue):
    print(f"REMOVING QUEUE {experiment_queue.path}")
    experiment_queue.close()
