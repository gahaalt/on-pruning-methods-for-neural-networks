import argparse
import importlib
import pprint
import sys
import time

from tools import parser, utils

cprint = utils.get_cprint(color='red')

arg_parser = argparse.ArgumentParser(prefix_chars='-+')
arg_parser.add_argument("--dry",
                        action="store_true",
                        help="Skip execution but parse experiments")
arg_parser.add_argument("--exp",
                        default='experiment.yaml',
                        type=str,
                        help="Path to .yaml file with experiments")
arg_parser.add_argument("--pick",
                        "--cherrypick-experiments",
                        type=int,
                        nargs='*',
                        help="Run only selected experiments, e.g. 0 1 3 or just 1")
args, unknown_args = arg_parser.parse_known_args()

if unknown_args:
    cprint(f"UNKNOWN CMD ARGUMENTS: {unknown_args}")
else:
    cprint(f"ALL CMD ARGUMENTS RECOGNIZED! (len(sys.argv) = {len(sys.argv)})")

parameters = utils.filter_argv(unknown_args, include=['+'], exclude=['-'])
for p in parameters:
    sys.argv.remove(p)  # filter out parameters, leave only arguments

default_config, experiment_queue = parser.load_from_yaml(yaml_path=args.exp,
                                                         cmd_parameters=parameters)

for exp_idx, exp in enumerate(experiment_queue):
    if args.pick and exp_idx not in args.pick:
        cprint(f"SKIPPING EXPERIMENT {exp_idx} BY PICK")
        continue

    print()
    cprint(f"NEW EXPERIMENT {exp_idx}:")
    pprint.pprint(exp)
    if args.dry:
        continue
    if exp.name == "skip":
        cprint(f"SKIPPING EXPERIMENT {exp_idx} BY NAME")

    module = importlib.import_module(exp.module)
    exp.reset_unused_parameters(exclude=['REP', 'RND_IDX', 'global_repeat', 'repeat',
                                         'queue', 'module'])
    try:
        module.main(exp)
    except KeyboardInterrupt:
        cprint(f"\n\nSKIPPING EXPERIMENT {exp_idx}, WAITING 2 SECONDS BEFORE "
               f"RESUMING...")
        time.sleep(2)

if isinstance(experiment_queue, parser.YamlExperimentQueue):
    cprint(f"REMOVING QUEUE {experiment_queue.path}")
    experiment_queue.close()
