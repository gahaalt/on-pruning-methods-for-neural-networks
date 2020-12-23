# %%

import tqdm
import time
from experimental.toolkit import *
import tensorflow as tf
import numpy as np
from copy import deepcopy
from tools import models, datasets, utils
import tensorflow.keras.mixed_precision.experimental as mixed_precision

utils.set_memory_growth()
utils.set_precision(16)


def maybe_abs(mask):
    # return tf.abs(mask)
    return tf.identity(mask)


def mask_activation(mask):
    # return tf.tanh(mask)
    return tf.sigmoid(mask)


MaskedConv, MaskedDense = create_layers(tf.identity)


def regularize(values):
    loss = 0
    for value in values:
        processed_value = maybe_abs(value) + 10
        loss += tf.reduce_sum(processed_value) * mask_regularization
    return loss


mask_initial_value = 5.
mask_sampling = True


def set_kernel_masks_from_distributions(kernel_masks,
                                        distributions,
                                        mask_activation):
    for km, d in zip(kernel_masks, distributions):
        probs = mask_activation(d)
        sign = tf.cast(probs >= 0, probs.dtype)
        sign = sign * 2 - 1

        rnd = tf.random.uniform(shape=probs.shape, dtype=probs.dtype)
        km.assign(tf.cast(rnd <= tf.abs(probs), km.dtype) * sign)


schedule = tf.keras.optimizers.schedules.PiecewiseConstantDecay(
    boundaries=[4000, 12000],
    values=[1000.0, 100.0, 10.0])

mask_optimizer = mixed_precision.LossScaleOptimizer(
    tf.keras.optimizers.SGD(learning_rate=10.0, momentum=0.999, nesterov=True),
    loss_scale=2048)

############## CONFIG ENDS HERE
logger = Logger(column_width=10)

checkpoint_lookup = {
    '2k': 'data/partial_training_checkpoints/VGG19_2000it/0.h5',
    '8k': 'data/partial_training_checkpoints/VGG19_8000it/0.h5',
    '16k': 'data/partial_training_checkpoints/VGG19_16000it/0.h5',
    '2k2': 'data/partial_training_checkpoints/VGG19_2000it/1.h5',
    '8k2': 'data/partial_training_checkpoints/VGG19_8000it/1.h5',
    'full_from_2k': 'data/VGG19_IMP03_ticket/130735/0.h5',
    'unrl_full1': 'data/VGG19_full_training/70754/0.h5',
    'unrl_full2': 'data/VGG19_full_training/70754/1.h5',
    'perf': 'data/VGG19_IMP03_ticket/770423/10.h5',
    'perf2': 'data/VGG19_IMP03_ticket/775908/10.h5',
}

choosen_checkpoints = ['2k']

loss_fn = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True)

net = models.VGG(input_shape=(32, 32, 3), n_classes=10, version=19, l2_reg=1e-4,
                 DENSE_LAYER=MaskedDense, CONV_LAYER=MaskedConv)
perf_net = tf.keras.models.clone_model(net)
perf_net.load_weights(checkpoint_lookup['perf'])
perf_kernel_masks = get_kernel_masks(perf_net)

kernel_masks = get_kernel_masks(net)
mask_regularization = tf.Variable(0.)

############# IF MASK SAMPLING
if mask_sampling:
    mask_distributions = [tf.Variable(tf.ones_like(mask)) for mask in kernel_masks]
    mask_differentiable = kernel_masks + mask_distributions
    mask_updatable = mask_distributions + mask_distributions
else:
    mask_distributions = kernel_masks
    mask_differentiable = kernel_masks
    mask_updatable = kernel_masks

net.load_weights(checkpoint_lookup[choosen_checkpoints[0]])
set_kernel_masks_values(mask_distributions, mask_initial_value)
if mask_sampling:
    set_kernel_masks_from_distributions(kernel_masks, mask_distributions, mask_activation)

ds = datasets.cifar10(128, 128, shuffle=10000)


@tf.function
def valid_step(model, x, y):
    outs = model(x, training=False)
    outs = tf.cast(outs, tf.float32)
    loss = loss_fn(y, outs)
    logger['valid_loss'](loss)
    logger['valid_acc'](tf.keras.metrics.sparse_categorical_accuracy(y, outs))


@tf.function
def train_epoch(model, steps):
    for x, y in ds['train'].take(steps):
        train_step(model, x, y)
        tf.numpy_function(update_pbar, inp=[], Tout=[])


@tf.function
def valid_epoch(model):
    for x, y in ds['valid']:
        valid_step(model, x, y)


def update_pbar():
    pbar.update(1)
    pbar.set_postfix(logger.peek('full_loss', 'train_loss',
                                 'train_acc', 'max_gradient'), refresh=False)


set_kernel_masks_from_distributions(kernel_masks,
                                    mask_distributions,
                                    mask_activation)
valid_epoch(net)
mask = update_mask_info(mask_distributions, mask_activation, logger)
f1, prc, rec, thr, density = compare_masks(perf_kernel_masks, mask_distributions,
                                           mask_activation=mask_activation)
logger['f1_to_perf'] = f1
logger['rec_to_perf'] = rec
logger['thr_to_perf'] = thr
logger['f1_density'] = density
logger.show()

# %%

schedule = tf.keras.optimizers.schedules.PiecewiseConstantDecay(
    boundaries=[32000, 48000, 64000],
    values=[0.1, 0.02, 0.004, 0.0008]
)
kernel_optimizer = tf.keras.optimizers.SGD(schedule, momentum=0.9, nesterov=True)
all_differentiable = mask_differentiable + net.trainable_weights
all_updatable = mask_updatable + net.trainable_weights


@tf.function
def train_step(model, x, y):
    if mask_sampling:
        set_kernel_masks_from_distributions(kernel_masks,
                                            mask_distributions,
                                            mask_activation)
    with tf.GradientTape() as tape:
        tape.watch(mask_differentiable)
        outs = model(x, training=True)
        outs = tf.cast(outs, tf.float32)
        loss = loss_fn(y, outs)
        logger['train_loss'](loss)

        loss += regularize(mask_distributions)
        loss += tf.add_n(model.losses)
        logger['full_loss'](loss)
        scaled_loss = mask_optimizer.get_scaled_loss(loss)

    scaled_grads = tape.gradient(target=scaled_loss, sources=all_differentiable)
    grads = mask_optimizer.get_unscaled_gradients(scaled_grads)

    max_gradient = tf.reduce_max([tf.reduce_max(tf.abs(grad)) for grad in grads])
    logger['train_acc'](tf.keras.metrics.sparse_categorical_accuracy(y, outs))
    logger['max_gradient'](max_gradient)

    mask_gradients = grads[:len(mask_differentiable)]
    kernel_gradients = grads[len(mask_differentiable):]

    if callable(mask_optimizer.lr):
        mask_gradients = clip_many(mask_gradients, clip_at=0.1 / mask_optimizer.lr(mask_optimizer.iterations))
    else:
        mask_gradients = clip_many(mask_gradients, clip_at=0.1 / mask_optimizer.lr)
    kernel_optimizer.apply_gradients(zip(kernel_gradients, net.trainable_weights))
    mask_optimizer.apply_gradients(zip(mask_gradients, mask_updatable))
    clip_many(mask_distributions, clip_at=10, inplace=True)


# %%

EPOCHS = 40
STEPS = 2000

regularizer_schedule = {
    0: 1e-7,
    # 4: 2e-7,
    # 6: 3e-7,
    # 7: 4e-7,
    # 9: 5e-7,
    # 10: 6e-7,
    # 11: 7e-7,
    # 12: 8e-7,
    # 13: 9e-7,
    # 14: 1e-6,
}

pbar = tqdm.tqdm(total=EPOCHS * STEPS, position=0, mininterval=0.5)

for epoch in range(EPOCHS):
    if epoch in regularizer_schedule:
        mask_regularization.assign(regularizer_schedule[epoch])

    t0 = time.time()
    train_epoch(net, STEPS)
    valid_epoch(net)
    logger['epoch_time'] = time.time() - t0

    mask = update_mask_info(mask_distributions, mask_activation, logger)
    f1, prc, rec, thr, density = compare_masks(perf_kernel_masks, mask_distributions,
                                               mask_activation=mask_activation,
                                               # force_sparsity=0.98
                                               )
    logger['f1_to_perf'] = f1
    logger['rec_to_perf'] = rec
    logger['thr_to_perf'] = thr
    logger['f1_density'] = density

    print('\r', end='')
    logs = logger.show()
    visualize_masks(mask_distributions, mask_activation)
pbar.close()


net2 = tf.keras.models.clone_model(net)
set_all_weights_from_model(net2, net)
set_kernel_masks_values(get_kernel_masks(net2), mask_distributions)
get_kernel_masks(net2)

prune_and_save_model(net2, mask_activation, threshold=0.01,
                     path='temp/new_trune_workspace_ckp.h5')

# %%