import numpy as np
import tensorflow as tf
import matplotlib.pyplot as plt


def get_kernel_masks(model):
    return [w for w in model.weights if 'kernel_mask' in w.name]


def get_kernels(model):
    return [l.kernel for l in model.layers if hasattr(l, 'kernel')]


# def set_kernel_masks_value(model, masks):
#     for i, kernel in enumerate(get_kernel_masks(model)):
#         if isinstance(masks, int) or isinstance(masks, float):
#             mask = np.ones_like(kernel.numpy()) * masks
#         else:
#             mask = masks[i]
#         kernel.assign(mask)


def set_kernel_masks_values(masks, values):
    if isinstance(values, int) or isinstance(values, float):
        for mask in masks:
            mask.assign(np.ones_like(mask.numpy()) * values)
    else:
        for mask, value in zip(masks, values):
            mask.assign(value)


def set_kernel_masks_object(model, masks):
    layers = (l for l in model.layers if hasattr(l, 'kernel_mask'))
    for l, km in zip(layers, masks):
        l.kernel_mask = km


def clip_many(values, clip_at, inplace=False):
    if inplace:
        for v in values:
            v.assign(tf.clip_by_value(v, -clip_at, clip_at))
    else:
        r = []
        for v in values:
            r.append(tf.clip_by_value(v, -clip_at, clip_at))
        return r


def visualize_masks(masks, mask_activation):
    fig, axes = plt.subplots(5, 1, figsize=(7, 20), constrained_layout=True)
    masks = [mask.numpy().flatten() for mask in masks]

    c = np.concatenate(masks[:4])
    axes[0].hist(c, bins=30)
    axes[1].hist(mask_activation(c).numpy(), bins=30)

    c = np.concatenate(masks)
    axes[2].hist(c, bins=30)
    axes[3].hist(mask_activation(c).numpy(), bins=30)

    means = [np.mean(np.abs(mask_activation(mask).numpy())) for mask in masks]
    axes[4].bar(range(len(means)), means)
    fig.show()
    return c


def create_logger(*keys):
    return {key: tf.keras.metrics.Mean() for key in keys}


logger_columns = []


def show_logger_results(logger, colwidth=10):
    results = {}
    for key, value in logger.items():
        if hasattr(value, 'result'):
            results[key] = value.result().numpy()
            value.reset_states()
        else:
            results[key] = value
    p = []
    for key, value in results.items():
        p.append(f"{str(value)[:colwidth].ljust(colwidth)}")

    global logger_columns
    new_logger_columns = list(logger.keys())
    if new_logger_columns != logger_columns:
        logger_columns = new_logger_columns
        show_logger_columns(logger, colwidth)

    print(*p, sep=' | ')
    return results


def show_logger_columns(logger, colwidth=10):
    p = []
    for key, value in logger.items():
        if len(key) > colwidth:
            p.append(f"{key[:((colwidth - 1) // 2 + (colwidth - 1) % 2)].upper()}-"
                     f"{key[-((colwidth - 1) // 2):].upper()}")
        else:
            p.append(f"{key.upper().ljust(colwidth)}")
    print(*p, sep=' | ')


def update_mask_info(kernel_masks, mask_activation, logger=None):
    mask = np.concatenate([
        tf.abs(mask_activation(mask)).numpy().flatten()
        for mask in kernel_masks
    ])
    if logger:
        logger['density'] = np.mean(mask)
        logger['mask_std'] = np.std(mask)
    return mask


def compare_masks(perf_m, m, mask_activation, force_sparsity=None):
    from sklearn.metrics import precision_recall_curve
    m = np.concatenate([x.numpy().flatten() for x in m])
    m = np.abs(mask_activation(m).numpy())

    perf_m = np.concatenate([x.numpy().flatten() for x in perf_m])

    prc, rec, thr = precision_recall_curve(perf_m, m)
    f1_scores = [2 * p * r / (p + r) if (p + r) else -1 for p, r in zip(prc, rec)]
    idx = np.argmax(f1_scores)

    if force_sparsity:  # modify `idx` so sparsity is as required
        threshold = np.sort(m)[int(len(m) * force_sparsity)]
        for idx, t in enumerate(thr):
            if t > threshold:
                break

    f1_density = np.mean(m >= thr[idx])
    return f1_scores[idx], prc[idx], rec[idx], thr[idx], f1_density


def create_layers(mask_activation):
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

        def call(self, x):
            multipler = mask_activation(self.kernel_mask)
            masked_w = tf.multiply(self.kernel, multipler)
            result = tf.matmul(x, masked_w)

            if self.use_bias:
                result = tf.add(result, self.bias)
            return self.activation(result)

        def set_pruning_mask(self, new_mask: np.ndarray):
            tf.assert_equal(new_mask.shape, self.kernel_mask.shape)
            self.kernel_mask.assign(new_mask)

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

        def call(self, x):
            multipler = mask_activation(self.kernel_mask)
            masked_w = tf.multiply(self.kernel, multipler)
            result = tf.nn.conv2d(x, masked_w, strides=self.strides, padding=self.padding.upper())

            if self.use_bias:
                result = tf.add(result, self.bias)
            return self.activation(result)

        def set_pruning_mask(self, new_mask: np.ndarray):
            tf.assert_equal(new_mask.shape, self.kernel_mask.shape)
            self.kernel_mask.assign(new_mask)

        def apply_pruning_mask(self):
            self.kernel.assign(tf.multiply(self.kernel, self.kernel_mask))

    return MaskedConv, MaskedDense
