import argparse
import os
import random
from collections.abc import Iterable
from copy import deepcopy

import yaml

from tools import utils

cprint = utils.get_cprint(color='yellow')


class YamlExperimentQueue:
    def __init__(self, experiments=None, path='.queue.yaml'):
        self.path = path
        if experiments:  # if None, can just read existing experiments
            self.write_content(experiments)
        else:
            assert os.path.exists(path), "Neither experiments or queue were given!"
            raise NotImplementedError("UNTESTED!")

    def read_content(self):
        with open(self.path, 'r') as f:
            z = list(yaml.safe_load_all(f))
        return [utils.ddict(exp) for exp in z]

    def write_content(self, exps):
        assert isinstance(exps, Iterable)
        with open(self.path, 'w') as f:
            nexps = map(utils.unddict, exps)  # because cannot dump ddict
            yaml.safe_dump_all(nexps, stream=f, sort_keys=False)

    def append_content(self, exps):
        existing_content = self.read_content()
        exps = existing_content + exps
        self.write_content(exps)

    def __bool__(self):
        z = self.read_content()
        return bool(z)

    def pop(self):
        if self:  # else is empty
            exps = self.read_content()
        else:
            return None
        exp = exps.pop(0)
        self.write_content(exps)
        return exp

    def __iter__(self):
        cprint(f"LOADING EXPERIMENT FROM {self.path}")
        while self:
            exp = self.pop()
            yield exp

    def close(self):
        os.remove(self.path)


def cool_parse_exp(exp, E, scopes=[]):
    keys = list(exp.keys())
    assert 'temp' not in keys
    assert 'E' not in keys

    for k in keys:
        v = exp[k]

        if isinstance(v, dict):
            nscopes = deepcopy(scopes)
            nscopes.append(exp)
            parsed_v = cool_parse_exp(v, E, nscopes)
            exp[k] = parsed_v
            continue

        if isinstance(v, str) and v.startswith('eval'):
            org_expr = v
            v = v[4:].strip()

            scope = {}  # populating the scope for eval
            for new_scope in scopes:  # for each parent scope
                scope.update(new_scope)  # update current
            scope.update(deepcopy(exp))  # top it with this level scope
            scope['E'] = E  # and add experiment history

            v = eval(v, {}, scope)
            cprint(f"FANCY PARSING {k}: {org_expr} --> {v}")

        if isinstance(v, str):
            try:
                v = float(v)
            except (ValueError, TypeError):
                pass
        exp[k] = v
    return exp


def load_from_yaml(yaml_path, cmd_parameters):
    parser = argparse.ArgumentParser(prefix_chars='+')
    for arg in cmd_parameters:
        if arg[0] == '+':
            if '=' in arg:
                arg = arg[:arg.index('=')]  # for usage with +arg=V
            parser.add_argument(arg)

    args = parser.parse_args(cmd_parameters)
    new_cmd_parameters = utils.ddict()

    for key, value in args.__dict__.items():
        try:  # for parsing integers etc
            new_cmd_parameters[key] = eval(value, {}, {})
        except (NameError, SyntaxError):  # for parsing strings
            new_cmd_parameters[key] = value
    cprint(f"CMD PARAMETERS: {new_cmd_parameters}")

    experiments = yaml.safe_load_all(open(yaml_path, "r"))
    experiments = [utils.ddict(exp) for exp in experiments]
    default = experiments.pop(0)
    default.update(new_cmd_parameters)

    all_unpacked_experiments = []
    for global_rep in range(default.get("global_repeat") or 1):
        unpacked_experiments = []
        for exp in experiments:
            # ORDER IS DEFINED HERE (important for fancy parsing)
            # 1. experiment
            # 2. defaults
            nexp = deepcopy(exp)
            defcpy = deepcopy(default)
            for key in nexp:
                if key in defcpy:
                    defcpy.pop(key)  # necessary to preserve order in dict
            nexp.update(defcpy)

            if "RND_IDX" in nexp:  # allow inserting RND_IDX
                rnd_idx = nexp["RND_IDX"]
            else:
                rnd_idx = random.randint(100000, 999999)

            for rep in range(exp.get("repeat") or 1):
                nexp_rep = deepcopy(nexp)
                nexp_rep["RND_IDX"] = rnd_idx
                nexp_rep["REP"] = rep

                nexp_rep = cool_parse_exp(nexp_rep, unpacked_experiments)
                unpacked_experiments.append(nexp_rep)
        all_unpacked_experiments.extend(unpacked_experiments)

    if path := default.queue:
        queue = YamlExperimentQueue(all_unpacked_experiments, path=path)
    else:
        queue = iter(all_unpacked_experiments)
    cprint(f"QUEUE TYPE: {type(queue)}")
    return default, queue
