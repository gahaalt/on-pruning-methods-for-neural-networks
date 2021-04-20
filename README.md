# Defining experiments

There's a single file: **experiments** that defines entire set of experiments. Its first element is always **default config** which contains default values for later experiments. If a settings repeats between **default config** and experiments, experiments have the priority.

**Special names**

1. `REPEAT`: copies a single experiment many times **before** fancy parsing, can be used for iterative trainings. If used on two experiments: `1, 1, 2, 2`
2. `GLOBAL_REPEAT`: performs all listed experiments many times. If used on two experiments: `1, 2, 1, 2`
3. `REP`: is added by `run.py` and is a repetition index in range `[0, REPEAT-1]`
4. `RND_IDX`: is added by `run.py` and can be used to uniquely identify an experiment. If already present in experiment, won't overwrite with random value

Modules should generally use the following parameters:

* `steps`: total number of steps in the training
* `steps_per_epoch`
* `model` and `model_config`
* `dataset` and `dataset_config`
* `optimizer` and `optimizer_config`
* `full_path`: location of `tensorboard` logs
* `yaml_logdir`: location of simpler `.yaml` logs
* `checkpoint`: location of tensorflow checkpoints

**Minimal experiment**

```
REPEAT: 1
GLOBAL_REPEAT: 1
precision: 32
queue: null
name: ...
module: ...
```

But modules usually require much more parameters, e.g. as listed above.

# Running experiments

Script `run.py` launches trainings specified in **experiments**. If `queue` parameter is specified as a valid path, the queue of the experiments will be stored as a yaml file and can be modified when experiments are running. Otherwise, queue is stored in RAM memory and cannot be modified.

1. You can use arbitrary flag with `=`, like `--queue=queue.yaml` or `--precision=32` to update **global config** straight from command line.

2. If experiment is stopped with `KeyboardInterrupt`, there will be 2 second pause during which `run.py` can be interrupted completely. If not interrupted completely, next experiment in the queue will start instead. Interrupted experiments will not leave any checkpoints.

3. If `name: skip`, training will not be performed, but experiment parameters can be used in fancy parsing. Skipped experiments will not leave any checkpoints.

4. `run.py` has command line arguments. If an argument does not affect experimental results, it should be a command line argument, otherwise it should be placed in **experiments** file. Command line arguments are intended for hardware settings. Modules might contain additional command line arguments.
   ```
   > python run.py --help
    optional arguments:
      -h, --help            show this help message and exit
      --exp EXP             Path to .yaml file with experiments
      --dry                 Skip execution but parse experiments
      --pick PICK, --cherrypick-experiments PICK
                            Run only selected experiments, e.g. 0,1,3 or 1
   ```

# Modules

They contain code for running the experiment and they use parameters from **experiments** file. They might define their own command line arguments and experiment parameters.

[Available modules](modules/README.md)

# Python `run.py`

`run.py` is parsing the experiments and running a module. It is the module from `modules` directory that does all the training. Module should be specified as a parameter in **default config**. Before module starts the training, experiments will be parsed...

# Fancy parsing with `eval`

> **WARNING**: `eval` is considered unsafe, keep your `experiment.yaml` safe

All values for experiments can be specified explicitly in `experiment.yaml`, e.g. `sparsity: 0.9`, but there are some tricks to simplify longer and more complicated experiments.

Fancy parsing allows you to execute python code during parsing. To do this, you need to type `eval` in the beginning of a parameter value. With this, you can do super cool tricks...

#### Tricks:

1. `odd_name: eval '\'.join([directory, name])` will work as in Python, value will be executed using `eval` function with variable scope from current experiment. In special cases, if `directory` value starts with `eval` too, `directory` should be resolved before `odd_name`. **Default config** is resolved at the end.

2. `sparsity: eval 0.5 * E[-1].sparsity` will be parsed as half of the `sparsity` value from the previous experiment in the queue. Before running `eval`, list `E` is added to the scope which allows access to previous experiments.

3. You can access values from nested dictionaries:

```
pruning_config:
   odd_config:
      sparsity: 0.5
---
sparsity: eval E[-1].pruning_config.odd_config.sparsity
pruning_config:
   sparsity: eval E[-1].pruning_config.odd_config.sparsity
```

4. You can access values from shallower levels:

```
abc: 1
nested:
   abc: 2
   nested2:
      test: eval abc
```

This will work and will reduce to `tested: 2`. Deeper levels have the priority.

5. Other examples:

```
name: test
---
model: VGG
name: test2
directory: eval f"{name}/{name[-1]}/{model}"
```

> Resulting `directory` value will be `test2/test/VGG`

```
list: [1, 2, 3]
---
list: [2, 3, 4]
number2: eval list[0]
number3: eval E[-1].list[2]
```

> Resulting `number2` value will be `2` and `number3` value will be `3`.

```
nested:
   test: 1

incremented: eval nested.test + 1
```

> Resulting `incremented` value will be `2`.

```
# DEFAULT CONFIG
test1: eval test3 + 1
---
test2: 5
test3: eval test2 - 1
```

> Correct. Eval from **default config** is solved at the end - `test3: 4`, `test1: 5`.

Following examples **won't work**

```
test3: eval test2 - 1  # ERROR: test2 IS UNKNOWN (WRONG ORDER)
test2: 5
```

```
# DEFAULT CONFIG
test1: 1
---
test2: eval test1 # ERROR: test1 IS UNKNOWN (WRONG ORDER)
```

Order can be important.

## Logs management

Logs in `.yaml` format should be saved by a module in location passed as `experiment.yaml/yaml_logdir`. These should contain experiment formulation and basic information about the results, e.g. accuracy. Following tool can recursively collect logs from `.yaml` files in subdirectories of `path`.

```
collect_logs.py 
   --path=[will be recursively serached for .yaml logs] 
   --dest=[where cumulative log will be saved, end it with .yaml]
```

Examples:

```
python -m tools.collect_logs.py 
   --path=data/VGG19_IMP03_ticket 
   --dest=data/VGG19_IMP03_ticket/collected_logs.yaml
```

```
python -m tools.collect_logs.py 
   -p=data/VGG19_IMP03_ticket 
   -d=collected_logs.yaml
```

```
python -m tools.collect_logs.py 
   -p=data/VGG19_IMP03_ticket 
```

By default, `--dest` sets itself to the same value as `--path`.
