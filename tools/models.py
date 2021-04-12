import tensorflow as tf
from tools.layers import MaskedConv, MaskedDense, GumbelMaskedConv, GumbelMaskedDense

DENSE_LAYER = MaskedDense
CONV_LAYER = MaskedConv


class GemPool(tf.keras.layers.Layer):
    def __init__(self, pool_size=None, initial_value=3.0):
        super().__init__()
        self.initial_value = initial_value
        self.pool = pool_size

    def call(self, flow, **kwargs):
        input_dtype = flow.dtype
        flow = tf.cast(flow, tf.float32)
        flow = tf.clip_by_value(flow, 1e-6, 1e3)
        self.p.assign(tf.clip_by_value(self.p, 1, 6))

        flow = tf.pow(flow, self.p)

        if self.pool:
            flow = tf.keras.layers.AvgPool2D(self.pool, padding='same',
                                             dtype='float32')(flow)
        else:
            flow = tf.keras.layers.GlobalAvgPool2D(dtype='float32')(flow)

        flow = tf.pow(flow, 1. / self.p)
        return tf.cast(flow, input_dtype)

    def build(self, *args):
        self.p = tf.Variable(self.initial_value, trainable=True, name='gempool_p',
                             dtype='float32')
        super().build(*args)


def classifier(flow,
               n_classes,
               regularizer=None,
               bias_regularizer=None,
               initializer='glorot_uniform',
               pooling='avgpool',
               DENSE_LAYER=DENSE_LAYER
               ):
    if pooling == 'catpool':
        maxp = tf.keras.layers.GlobalMaxPool2D()(flow)
        avgp = tf.keras.layers.GlobalAvgPool2D()(flow)
        flow = tf.keras.layers.Concatenate()([maxp, avgp])

    if pooling == 'avgpool':
        flow = tf.keras.layers.GlobalAvgPool2D()(flow)

    if pooling == 'maxpool':
        flow = tf.keras.layers.GlobalMaxPool2D()(flow)

    if pooling == 'gempool':
        flow = GemPool(initial_value=3.0)(flow)

    # multiple-head version
    if hasattr(n_classes, '__len__'):
        outs = [
            DENSE_LAYER(n_class,
                        bias_regularizer=bias_regularizer,
                        kernel_regularizer=regularizer,
                        kernel_initializer=initializer)(flow) for n_class in
            n_classes
        ]
    else:
        outs = DENSE_LAYER(n_classes,
                           bias_regularizer=bias_regularizer,
                           kernel_regularizer=regularizer,
                           kernel_initializer=initializer)(flow)
    return outs


def VGG(input_shape,
        n_classes,
        version=None,
        l1_reg=0,
        l2_reg=0,
        group_sizes=(1, 1, 2, 2, 2),
        features=(64, 128, 256, 512, 512),
        pools=(2, 2, 2, 2, 2),
        regularize_bias=True,
        DENSE_LAYER=DENSE_LAYER,
        CONV_LAYER=CONV_LAYER,
        **kwargs):
    if kwargs:
        print(f"VGG: unknown parameters: {kwargs.keys()}")
    if version:
        if version == 11:
            group_sizes = (1, 1, 2, 2, 2)
        elif version == 13:
            group_sizes = (2, 2, 2, 2, 2)
        elif version == 16:
            group_sizes = (2, 2, 3, 3, 3)
        elif version == 19:
            group_sizes = (2, 2, 4, 4, 4)
        else:
            raise KeyError(f"Unkown version={version}!")

    regularizer = tf.keras.regularizers.l1_l2(l1_reg, l2_reg) if l2_reg or l1_reg else None
    bias_regularizer = regularizer if regularize_bias else None

    def conv3x3(*args, **kwargs):
        # bias is not needed, since batch norm does it
        return CONV_LAYER(
            *args,
            **kwargs,
            kernel_size=3,
            padding="same",
            use_bias=False,
            kernel_regularizer=regularizer,
        )

    def bn_relu(x):
        x = tf.keras.layers.BatchNormalization(
            beta_regularizer=bias_regularizer, gamma_regularizer=bias_regularizer
        )(x)
        return tf.keras.layers.ReLU()(x)

    inputs = tf.keras.layers.Input(shape=input_shape)
    flow = inputs

    skip_first_maxpool = True
    for group_size, width, pool in zip(group_sizes, features, pools):

        if not skip_first_maxpool:
            flow = tf.keras.layers.MaxPool2D(pool)(flow)
        else:
            skip_first_maxpool = False

        for _ in range(group_size):
            flow = conv3x3(filters=width)(flow)
            flow = bn_relu(flow)

    outs = classifier(flow,
                      n_classes,
                      regularizer=regularizer,
                      bias_regularizer=bias_regularizer,
                      DENSE_LAYER=DENSE_LAYER)
    model = tf.keras.Model(inputs=inputs, outputs=outs)
    return model


def ResNet(
        input_shape,
        n_classes,
        version=None,
        l1_reg=0,
        l2_reg=0,
        bootleneck=False,
        strides=(1, 2, 2),
        group_sizes=(2, 2, 2),
        features=(16, 32, 64),
        initializer='he_uniform',
        activation='tf.nn.relu',
        final_pooling='avgpool',
        dropout=0,
        bn_ends_block=False,
        regularize_bias=True,
        remove_first_relu=False,  # not tested
        pyramid=False,  # linear PyramidNet
        head=(
                ('conv', 16, 3, 1),),
        **kwargs
):
    if version:
        raise KeyError("Versions not defined yet!")
    if kwargs:
        print(f"ResNet: unknown parameters: {kwargs.keys()}")

    exec_outs = {}
    exec(f'var = {activation}', None, exec_outs)
    activation = exec_outs.pop('var')

    regularizer = tf.keras.regularizers.l1_l2(l1_reg, l2_reg) if l2_reg or l1_reg else None
    bias_regularizer = regularizer if regularize_bias else None

    def conv(filters, kernel_size, use_bias=False, **kwargs):
        return CONV_LAYER(filters,
                          kernel_size,
                          padding='same',
                          use_bias=use_bias,
                          kernel_initializer=initializer,
                          kernel_regularizer=regularizer,
                          bias_regularizer=bias_regularizer,
                          **kwargs)

    def shortcut(x, filters, strides):
        if x.shape[-1] != filters or strides != 1:
            return CONV_LAYER(filters,
                              kernel_size=1,
                              use_bias=False,
                              strides=strides,
                              kernel_initializer=initializer,
                              kernel_regularizer=regularizer)(x)
        else:
            return x

    def shortcut_pyramid(x, filters, strides):
        if strides != 1:
            x = tf.keras.layers.AvgPool2D(strides)(x)

        to_pad = filters - x.shape[-1]
        return tf.pad(x, ((0, 0), (0, 0), (0, 0), (0, to_pad))) if to_pad else x

    def bn_relu(x, remove_relu=False):
        x = tf.keras.layers.BatchNormalization(beta_regularizer=bias_regularizer,
                                               gamma_regularizer=bias_regularizer)(x)
        return x if remove_relu else activation(x)

    def simple_block(flow, filters, strides):
        if preactivate_block:
            flow = bn_relu(flow, remove_first_relu)

        flow = conv(filters, 3, strides=strides)(flow)
        flow = bn_relu(flow)

        if dropout:
            flow = tf.keras.layers.Dropout(dropout)(flow)
        flow = conv(filters, 3, strides=1)(flow)

        if bn_ends_block:
            flow = bn_relu(flow, remove_relu=True)
        return flow

    def bootleneck_block(flow, filters, strides):
        if preactivate_block:
            flow = bn_relu(flow, remove_first_relu)

        flow = conv(filters // 4, 1)(flow)
        flow = conv(filters // 4, 3, strides=strides)(bn_relu(flow))
        flow = conv(filters, 1)(bn_relu(flow))

        if bn_ends_block:
            flow = bn_relu(flow, remove_relu=True)
        return flow

    if bootleneck:
        block = bootleneck_block
    else:
        block = simple_block

    inputs = tf.keras.Input(input_shape)
    flow = inputs

    # BUILDING HEAD OF THE NETWORK

    for name, *args in head:
        if name == 'conv':
            bias = True if 'bias' in args else False
            flow = conv(args[0], args[1], strides=args[2], use_bias=bias)(flow)
        if name == 'maxpool':
            flow = tf.keras.layers.MaxPool2D(args[0])(flow)
        if name == 'avgpool':
            flow = tf.keras.layers.AvgPool2D(args[0])(flow)
        if name == 'relu':
            flow = tf.nn.relu(flow)

    # BUILD THE RESIDUAL BLOCKS
    layer_idx, num_layers = 0, sum(group_sizes)
    for group_size, width, stride in zip(group_sizes, features, strides):
        flow = bn_relu(flow, remove_first_relu)
        preactivate_block = False

        for _ in range(group_size):
            layer_idx += 1

            if pyramid:
                if len(features) > 2:
                    print(f"PyramidNet ignored intermediate width in {features}")

                shortcut = shortcut_pyramid
                width = int(
                    (features[-1] - features[0]) * layer_idx / num_layers + features[0])

            residual = block(flow, width, stride)
            flow = residual + shortcut(flow, width, stride)
            preactivate_block = True
            stride = 1

    # BUILDING THE CLASSIFIER
    flow = bn_relu(flow, remove_relu=True)
    flow = tf.nn.relu(flow)

    outs = classifier(flow,
                      n_classes,
                      regularizer=regularizer,
                      bias_regularizer=bias_regularizer,
                      initializer=initializer,
                      pooling=final_pooling)
    model = tf.keras.Model(inputs=inputs, outputs=outs)
    return model


def WRN(N, K, *args, **kwargs) -> tf.keras.Model:
    """args, kwargs parameters:
        * input_shape,
        * n_classes,
        * l2_reg=0,
        * bootleneck=False,
        * strides=(1, 2, 2),
        * initializer='he_uniform',
        * activation='tf.nn.relu',
        * final_pooling='avgpool',
        * dropout=0,
        * bn_ends_block=False,
        * regularize_bias=True,
        * remove_first_relu=False,  # not tested
        * pyramid=False,  # linear PyramidNet
        * head=(('conv', 16, 3, 1),))
    :param N: Number of layers
    :param K: How wider should the network be
    :return: tf.keras compatible model
    """
    assert (N - 4) % 6 == 0
    size = int((N - 4) / 6)
    return ResNet(*args, group_sizes=(size, size, size),
                  features=(16 * K, 32 * K, 64 * K), **kwargs)


def LeNet(input_shape,
          n_classes,
          l1_reg=0,
          l2_reg=0,
          layer_sizes=(300, 100),
          initializer='glorot_uniform',
          **kwargs):
    if kwargs:
        print(f"LeNet: unknown parameters: {kwargs.keys()}")
    regularizer = tf.keras.regularizers.l1_l2(l1_reg, l2_reg) if l2_reg or l1_reg else None
    initializer = initializer

    def dense(*args, **kwargs):
        return DENSE_LAYER(*args,
                           **kwargs,
                           kernel_initializer=initializer,
                           kernel_regularizer=regularizer)

    inputs = tf.keras.layers.Input(shape=input_shape)

    flow = tf.keras.layers.Flatten()(inputs)
    for layer_size in layer_sizes:
        flow = dense(layer_size, activation='relu')(flow)

    outs = dense(n_classes, activation=None)(flow)
    model = tf.keras.Model(inputs=inputs, outputs=outs)
    return model


def LeNetConv(input_shape,
              n_classes,
              l1_reg=0,
              l2_reg=0,
              initializer='glorot_uniform',
              **kwargs):
    if kwargs:
        print(f"Unknown parameters: {kwargs}")
    regularizer = tf.keras.regularizers.l1_l2(l1_reg, l2_reg) if l2_reg or l1_reg else None
    initializer = initializer

    def dense(*args, **kwargs):
        return DENSE_LAYER(*args,
                           **kwargs,
                           kernel_initializer=initializer,
                           kernel_regularizer=regularizer)

    def conv(*args, **kwargs):
        return CONV_LAYER(*args,
                          **kwargs,
                          kernel_initializer=initializer,
                          kernel_regularizer=regularizer)

    inputs = tf.keras.layers.Input(shape=input_shape)

    flow = conv(20, 5, activation='relu')(inputs)
    flow = tf.keras.layers.MaxPool2D(2)(flow)
    flow = conv(50, 5, activation='relu')(flow)
    flow = tf.keras.layers.MaxPool2D(2)(flow)

    flow = tf.keras.layers.Flatten()(flow)
    flow = dense(500, activation='relu')(flow)

    outs = dense(n_classes, activation=None)(flow)
    model = tf.keras.Model(inputs=inputs, outputs=outs)
    return model


def get_model(model_name):
    if model_name.lower() in ['vgg']:
        return VGG
    elif model_name.lower() in ['resnet']:
        return ResNet
    elif model_name.lower() in ['wrn', 'wide_resnet', 'wide resnet']:
        return WRN
    elif model_name.lower() in ['lenet', 'dense lenet', 'dense_lenet']:
        return LeNet
    else:
        raise KeyError(f'MODEL {model_name} WAS NOT RECOGNIZED!')
