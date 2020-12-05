import time

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf

from tools import datasets, models, pruning, utils

utils.set_memory_growth()


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
        mask = tf.sigmoid(self.kernel_mask)
        masked_w = tf.multiply(self.kernel, mask)
        # masked_w = masked_w / tf.reduce_mean(self.kernel_mask)

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
        mask = tf.sigmoid(self.kernel_mask)
        masked_w = tf.multiply(self.kernel, mask)
        # masked_w = masked_w / tf.reduce_mean(self.kernel_mask)

        result = tf.nn.conv2d(
            x, masked_w, strides=self.strides, padding=self.padding.upper()
        )

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


# %%

ds = datasets.cifar10(128, 128, shuffle=20000)
optimizer = tf.optimizers.SGD(learning_rate=100, momentum=0.99, nesterov=True)
loss_fn = tf.losses.SparseCategoricalCrossentropy(True)

model = models.VGG((32, 32, 3), n_classes=10, version=19,
                   CONV_LAYER=MaskedConv, DENSE_LAYER=MaskedDense)
model.load_weights('temp/refactored_11.30/VGG19iterative_truning_init8000/43949/0.h5')

full_loss_metric = tf.metrics.Mean()
loss_metric = tf.metrics.SparseCategoricalCrossentropy()
accu_metric = tf.metrics.SparseCategoricalAccuracy(True)

kernels = [layer.kernel for layer in model.layers if hasattr(layer, "kernel")]
kernel_masks = [w for w in model.weights if "kernel_mask" in w.name]
for kernel in kernel_masks:
    kernel.assign(np.ones_like(kernel.numpy()) * 3)

decay = 1e-6


def get_and_reset(metric):
    x = metric.result()
    metric.reset_states()
    return x


def reg_fn():
    loss = 0
    for mask in kernel_masks:
        loss += tf.reduce_sum(tf.sigmoid(mask))
    return loss


@tf.function
def train_step(x, y):
    with tf.GradientTape() as tape:
        tape.watch(kernel_masks)
        outs = model(x, training=True)
        loss = loss_fn(y, outs)
        loss += reg_fn() * decay

    loss_metric(y, outs)
    accu_metric(y, outs)
    full_loss_metric(loss)
    grads = tape.gradient(loss, kernel_masks)
    optimizer.apply_gradients(zip(grads, kernel_masks))

    for mask in kernel_masks:
        mask.assign(tf.clip_by_value(mask, -6, 6))


@tf.function
def valid_step(x, y):
    outs = model(x, training=False)
    loss_metric(y, outs)
    accu_metric(y, outs)


@tf.function
def valid_epoch(ds):
    for x, y in ds:
        valid_step(x, y)


def report_density(model, detailed=False):
    nonzero = 0
    max_nonzero = 0
    for layer in model.layers:
        if hasattr(layer, 'kernel_mask'):
            km = layer.kernel_mask
            km = tf.sigmoid(km).numpy()
            max_nonzero += km.size
            nonzero_here = km.sum()

            if detailed:
                print(f"density of {layer.name:>16}: {np.mean(km):6.4f}")
            nonzero += nonzero_here

    return nonzero / max_nonzero


valid_epoch(ds['valid'])
print(f"V LOSS: {get_and_reset(loss_metric):6.3f}",
      f"V ACCU: {get_and_reset(accu_metric):6.3f}",
      sep=' | ')

# %%

NUM_ITER = 16000
REP_ITER = 200
VAL_ITER = 2000

t0 = time.time()

for step, (x, y) in enumerate(ds['train']):
    train_step(x, y)

    if (step + 1) % REP_ITER == 0:
        print(
            f"STEP: {step + 1:^8}",
            f"T FULL: {get_and_reset(full_loss_metric):6.3f}",
            f"T LOSS: {get_and_reset(loss_metric):6.3f}",
            f"T ACCU: {get_and_reset(accu_metric):6.3f}",
            f"DENSITY: {report_density(model):6.3f}",
            f"TIME: {time.time() - t0:6.0f}",
            sep=' | ')

    if (step + 1) % VAL_ITER == 0:
        valid_epoch(ds['valid'])

        print(
            f"{'VALIDATION':^14}",
            f"V LOSS: {get_and_reset(loss_metric):6.3f}",
            f"V ACCU: {get_and_reset(accu_metric):6.3f}",
            f"DENSITY: {report_density(model):6.3f}",
            f"TIME: {time.time() - t0:6.0f}",
            sep=' | ')

        report_density(model, detailed=True)
        plt.hist(kernel_masks[2].numpy().flatten(), bins=40)
        plt.xlim(-10, 10)
        plt.show()

    if (step + 1) % NUM_ITER == 0:
        break

# %%

for km in kernel_masks:
    k = km.numpy()
    k[k < 0] = 0
    k[k > 0] = 1
    km.assign(k)

# %%

pruning.apply_pruning_for_model(model)

# %%

pruning.report_density(model, detailed=True)

# %%

model.save_weights("temp/new_truning1.h5")

# %%
