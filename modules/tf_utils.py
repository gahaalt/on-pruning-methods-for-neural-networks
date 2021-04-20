import argparse
from collections.abc import Iterable
from copy import deepcopy

import tensorflow as tf

from tools.utils import get_cprint

if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--gpu",
                            default=None,
                            type=str,
                            help="Which GPUs to use during training, e.g. 0,1,3 or 1")
    arg_parser.add_argument("--no-memory-growth",
                            action="store_true",
                            help="Disables memory growth")
    args, unknown_args = arg_parser.parse_known_args()
    if unknown_args:
        cprint(f"UNKNOWN CMD ARGUMENTS: {unknown_args}")

    if args.gpu is not None:
        gpus = tf.config.get_visible_devices("GPU")
        gpu_indices = [num for num in range(10) if str(num) in args.gpu]
        set_visible_gpu([gpus[idx] for idx in gpu_indices])

    if not args.no_memory_growth:
        set_memory_growth()

cprint = get_cprint(color='light blue')


def main(exp):
    cprint("RUNNING TENSORFLOW MODULE")
    set_precision(exp.precision)


# %%

# %%


def set_memory_growth():
    for gpu in tf.config.get_visible_devices('GPU'):
        tf.config.experimental.set_memory_growth(gpu, True)


def set_visible_gpu(gpus=[]):
    if isinstance(gpus, Iterable):
        tf.config.set_visible_devices(gpus, 'GPU')
    else:
        tf.config.set_visible_devices([gpus], 'GPU')


def set_precision(precision):
    import tensorflow.keras.mixed_precision.experimental as mixed_precision

    if precision == 16:
        policy = mixed_precision.Policy("mixed_float16")
        mixed_precision.set_policy(policy)


def logging_from_history(history, info):
    import tensorflow as tf
    import datetime

    full_path = info["full_path"]
    writer = tf.summary.create_file_writer(full_path)
    cprint(f"FULL PATH: {full_path}")

    maxi_acc = max(history["val_accuracy"])
    date = datetime.datetime.now()
    info["TIME"] = f"{date.year}.{date.month}.{date.day} {date.hour}:{date.minute}"
    info["ACC"] = maxi_acc

    with writer.as_default():
        for key in history:
            for idx, value in enumerate(history[key]):
                tf.summary.scalar(key, value, idx + 1)
        tf.summary.text("experiment", data=str(info), step=0)

    with open(f"{info['yaml_logdir']}", "a") as f:
        for k, v in info.items():
            print(f"{k}: {v}", file=f)
        print("---", file=f)
    cprint(f"BEST ACCURACY: {maxi_acc}")


def get_optimizer(optimizer, optimizer_config):
    config = deepcopy(optimizer_config)
    optimizer = eval(optimizer)  # string -> optimizer

    for k, v in config.items():
        config[k] = eval(f"{config[k]}")
    return optimizer(**config)


def get_kernels(model):
    return [l.kernel for l in model.layers if hasattr(l, 'kernel')]


def set_all_weights_from_model(model, source_model):
    """Warning if a pair doesn't match."""

    for w1, w2 in zip(model.weights, source_model.weights):
        if w1.shape == w2.shape:
            w1.assign(w2)
        else:
            print(f"WARNING: Skipping {w1.name}: {w1.shape} != {w2.shape}")


def clone_model(model):
    """tf.keras.models.clone_model + toolkit.set_all_weights_from_model"""

    new_model = tf.keras.models.clone_model(model)
    set_all_weights_from_model(new_model, model)
    return new_model


def reset_weights_to_checkpoint(model, ckp=None, skip_keyword=None):
    """Reset network in place, has an ability to skip keybword."""
    import tensorflow as tf

    temp = tf.keras.models.clone_model(model)
    if ckp:
        temp.load_weights(ckp)
    skipped = 0
    for w1, w2 in zip(model.weights, temp.weights):
        if skip_keyword in w1.name:
            skipped += 1
            continue
        w1.assign(w2)
    cprint(f"INFO RESET: Skipped {skipped} layers with keyword {skip_keyword}!")
    return skipped


def clip_many(values, clip_at, clip_from=None, inplace=False):
    """Clips a list of tf or np arrays. Returns tf arrays."""
    import tensorflow as tf

    if clip_from is None:
        clip_from = -clip_at

    if inplace:
        for v in values:
            v.assign(tf.clip_by_value(v, clip_from, clip_at))
    else:
        r = []
        for v in values:
            r.append(tf.clip_by_value(v, clip_from, clip_at))
        return r


def concatenate_flattened(arrays):
    import numpy as np
    return np.concatenate([x.flatten() if isinstance(x, np.ndarray) else x.numpy(

    ).flatten() for x in arrays], axis=0)
