# %%

import time

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf

from tools import datasets, models, utils
import tensorflow.keras.mixed_precision.experimental as mixed_precision

utils.set_memory_growth()
utils.set_precision(16)

MASK_ACTIVATION = tf.tanh
REG_ACTIVATION = tf.abs


class MaskedDense(tf.keras.layers.Dense):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def build(self, input_shape):
        super().build(input_shape)

        self.kernel_mask = self.add_weight(
            name="kernel_mask",
            shape=self.kernel.shape,
            dtype=self.kernel.dtype,
            initializer="ones",
            trainable=False,
        )
        self.sparsity = 1 - np.mean(self.kernel_mask.numpy())

    def call(self, x):
        mask = MASK_ACTIVATION(self.kernel_mask)
        masked_w = tf.multiply(self.kernel, mask)
        result = tf.matmul(x, masked_w)

        if self.use_bias:
            result = tf.add(result, self.bias)

        return self.activation(result)

    def set_pruning_mask(self, new_mask: np.ndarray):
        """
        :param new_mask: mask of the same shape as `layer.kernel`
        :return: None
        """
        tf.assert_equal(new_mask.shape, self.kernel_mask.shape)
        self.kernel_mask.assign(new_mask)
        self.sparsity = 1 - np.mean(self.kernel_mask.numpy())
        self.left_unpruned = np.sum(self.kernel_mask.numpy() == 1)

    def apply_pruning_mask(self):
        self.kernel.assign(tf.multiply(self.kernel, self.kernel_mask))


class MaskedConv(tf.keras.layers.Conv2D):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def build(self, input_shape):
        super().build(input_shape)

        self.kernel_mask = self.add_weight(
            name="kernel_mask",
            shape=self.kernel.shape,
            dtype=self.kernel.dtype,
            initializer="ones",
            trainable=False,
        )
        self.sparsity = 1 - np.mean(self.kernel_mask.numpy())

    def call(self, x):
        mask = MASK_ACTIVATION(self.kernel_mask)
        masked_w = tf.multiply(self.kernel, mask)
        result = tf.nn.conv2d(x, masked_w, strides=self.strides, padding=self.padding.upper())

        if self.use_bias:
            result = tf.add(result, self.bias)

        return self.activation(result)

    def set_pruning_mask(self, new_mask: np.ndarray):
        """
        :param new_mask: mask of the same shape as `layer.kernel`
        :return: None
        """
        tf.assert_equal(new_mask.shape, self.kernel_mask.shape)
        self.kernel_mask.assign(new_mask)
        self.sparsity = 1 - np.mean(self.kernel_mask.numpy())
        self.left_unpruned = np.sum(self.kernel_mask.numpy() == 1)

    def apply_pruning_mask(self):
        self.kernel.assign(tf.multiply(self.kernel, self.kernel_mask))


full_loss_metric = tf.metrics.Mean()
loss_metric = tf.metrics.SparseCategoricalCrossentropy(from_logits=True)
accu_metric = tf.metrics.SparseCategoricalAccuracy()
gradient_keeper = tf.metrics.Mean()


def get_and_reset(metric):
    x = metric.result()
    metric.reset_states()
    return x


def reg_fn(kernel_masks):
    loss = 0
    for mask in kernel_masks:
        loss += tf.reduce_sum(REG_ACTIVATION(mask))
    return loss


@tf.function
def train_step(model, kernel_masks, x, y):
    with tf.GradientTape() as tape:
        tape.watch(kernel_masks)
        outs = model(x, training=True)
        outs = tf.cast(outs, tf.float32)
        loss = model.loss(y, outs)

        loss += reg_fn(kernel_masks) * decay
        scaled_loss = model.mask_optimizer.get_scaled_loss(loss)

    loss_metric(y, outs)
    accu_metric(y, outs)
    full_loss_metric(loss)

    grads = tape.gradient(scaled_loss, kernel_masks)
    grads = optimizer.get_unscaled_gradients(grads)
    max_gradient = tf.reduce_max([tf.reduce_max(tf.abs(grad)) for grad in grads])
    gradient_keeper(max_gradient)

    grads = [tf.clip_by_value(grad,
                              -0.1 / float(optimizer.learning_rate),
                              0.1 / float(optimizer.learning_rate)) for grad in grads]
    optimizer.apply_gradients(zip(grads, kernel_masks))

    for mask in kernel_masks:
        mask.assign(tf.clip_by_value(mask, -10, 10))


@tf.function
def valid_step(model, x, y):
    outs = model(x, training=False)
    outs = tf.cast(outs, tf.float32)
    loss_metric(y, outs)
    accu_metric(y, outs)


@tf.function
def valid_epoch(model, ds):
    for x, y in ds:
        valid_step(model, x, y)


def report_average_mask(model, detailed=False, mask_activation=MASK_ACTIVATION):
    nonzero = 0
    max_nonzero = 0
    for layer in filter(lambda x: hasattr(x, 'kernel_mask'), model.layers):
        km = layer.kernel_mask.numpy()
        km = mask_activation(km).numpy()

        max_nonzero += km.size
        nonzero_here = km.sum()

        if detailed:
            print(f"density of {layer.name:>16}: {np.mean(km):6.4f}")
        nonzero += nonzero_here
    return nonzero / max_nonzero


# def compare_masks(perf_m, m, mask_activation=MASK_ACTIVATION, force_sparsity=None):
#     m = np.concatenate([x.numpy().flatten() for x in m])
#     m = mask_activation(m).numpy()
#
#     perf_m = np.concatenate([x.numpy().flatten() for x in perf_m])
#
#     prc, rec, thr = precision_recall_curve(perf_m, m)
#     f1_scores = [2 * p * r / (p + r) for p, r in zip(prc, rec)]
#     idx = np.argmax(f1_scores)
#
#     if force_sparsity:  # modify `idx` so sparsity is as required
#         threshold = np.sort(m)[int(len(m) * force_sparsity)]
#         for idx, t in enumerate(thr):
#             if t > threshold:
#                 break
#
#     f1_density = np.mean(m >= thr[idx])
#     return f1_scores[idx], prc[idx], rec[idx], thr[idx], f1_density
from tools.pruning_toolkit import compare_masks


def get_kernel_masks(model):
    return [w for w in model.weights if "kernel_mask" in w.name]


# %%

model_perf = models.VGG((32, 32, 3), n_classes=10, version=19)
model_perf.load_weights('data/VGG19_IMP03_ticket/770423/10.h5')
perf_kernel_masks = get_kernel_masks(model_perf)

ds = datasets.cifar10(128, 128, shuffle_train=10000)
optimizer = tf.optimizers.SGD(learning_rate=100, momentum=0.99, nesterov=True)
optimizer = mixed_precision.LossScaleOptimizer(optimizer, "dynamic")
loss_fn = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True)
learning_rate = float(optimizer.learning_rate)

model = models.VGG((32, 32, 3), n_classes=10, version=19,
                   CONV_LAYER=MaskedConv, DENSE_LAYER=MaskedDense)

checkpoint_lookup = {
    '2k': 'data/partial_training_checkpoints/VGG19_2000it/0.h5',
    '8k': 'data/partial_training_checkpoints/VGG19_8000it/0.h5',
    '16k': 'data/partial_training_checkpoints/VGG19_16000it/0.h5',
    '2k2': 'data/partial_training_checkpoints/VGG19_2000it/1.h5',
    '8k2': 'data/partial_training_checkpoints/VGG19_8000it/1.h5',
    'full_from_2k': 'data/VGG19_IMP03_ticket/130735/0.h5',
    'unrl_full1': 'data/VGG19_full_training/70754/0.h5',
    'unrl_full2': 'data/VGG19_full_training/70754/1.h5',
}

model.load_weights(checkpoint_lookup['8k'])
model.compile(optimizer, loss_fn)
kernel_masks = get_kernel_masks(model)

all_models = [model]

# initialize kernel_masks
for kernel in kernel_masks:
    kernel.assign(np.ones_like(kernel.numpy()) * 4.)

decay = tf.Variable(1e-6)

for m in all_models:
    valid_epoch(m, ds['valid'])
    print(f"V LOSS: {get_and_reset(loss_metric):6.3f}",
          f"V ACCU: {get_and_reset(accu_metric):6.4f}",
          sep=' | ')

plt.hist(np.concatenate([km.numpy().flatten() for km in kernel_masks[:3]]), bins=40)
plt.show()

print(compare_masks(perf_kernel_masks, kernel_masks, mask_activation=tf.identity))

# %%

decays = []
decay.assign(1e-7)

NUM_ITER = 4800
VAL_ITER = 600
REP_ITER = 600
force_sparsity = None

t0 = time.time()

absactiv = lambda x: tf.abs(MASK_ACTIVATION(x))

for step, (x, y) in enumerate(ds['train']):
    for m in all_models:
        train_step(m, kernel_masks, x, y)

    if (step + 1) % REP_ITER == 0:
        # print(get_and_reset(mymean))
        mean_density = report_average_mask(model, mask_activation=absactiv)
        f1, prc, rec, thr, f1d = compare_masks(perf_kernel_masks, kernel_masks,
                                               mask_activation=absactiv,
                                               force_sparsity=force_sparsity
                                               )
        print(
            f"IT{step + 1:^6}",
            f"F LOS {get_and_reset(full_loss_metric):6.3f}",
            f"LOS {get_and_reset(loss_metric):6.3f}",
            f"ACC {get_and_reset(accu_metric):6.4f}",
            f"AVGMASK {mean_density:8.6f}",
            f"F1 {f1:6.4f}",
            # f"PRC {prc:6.4f}",
            f"REC {rec:6.4f}",
            f"THR {thr:6.3f}",
            f"GRAD {get_and_reset(gradient_keeper):6.4f}",
            f"DENS {f1d:6.3f}",
            f"T {time.time() - t0:6.0f}",
            sep=' | ')

        plt.figure(figsize=(5, 7), dpi=100)
        plt.subplot(2, 1, 1)
        plt.hist(np.concatenate([MASK_ACTIVATION(km).numpy().flatten() for km in kernel_masks[:4]]), bins=40)
        plt.subplot(2, 1, 2)
        plt.hist(np.concatenate([km.numpy().flatten() for km in kernel_masks[:4]]), bins=40)
        plt.show()

    if (step + 1) % VAL_ITER == 0:
        for m in all_models:
            valid_epoch(m, ds['valid'])
        print(
            f"{'VALIDATION':^14}",
            f"V LOSS: {get_and_reset(loss_metric):6.3f}",
            f"V ACCU: {get_and_reset(accu_metric):6.4f}",
            f"TIME: {time.time() - t0:6.0f}",
            sep=' | ')

        # report_average_mask(model, detailed=True, mask_activation=absactiv)
        model.save_weights(f'temp/new_trune_workspace_ckp.h5', save_format="h5")

        if decays:
            decay.assign(decays.pop(0))
            print("decay", decay.value())

    if (step + 1) % NUM_ITER == 0:
        break

# %%
