import tensorflow as tf

from modules import tf_helper
from modules.pruning import pruning_utils
from modules.tf_helper import datasets, models, tf_utils
from ._initialize import *


def main(exp):
    """
    PROCEDURES IN ORDER:
    1. Loading inherited module - tf_utils
    2. Creating dataset, model, optimizer
    3. Loading checkpoint Before Pruning
    4. Applying pruning
    5. Loading checkpoint After Pruning
    6. Pruning related procedures After Pruning
    7. Training

    EXPERIMENT KEYS:
    * load_model_before_pruning: not required
    * load_model_after_pruning: not required
    * ...
    """
    print("RUNNING PRUNING MODULE")
    tf_helper.main(exp)  # RUN INHERITED MODULES

    pruning_utils.globally_enable_pruning()

    model = exp.model
    loss_fn = exp.loss_fn
    dataset = exp.dataset
    optimizer = exp.optimizer

    metrics = ["accuracy"]

    lr_metric = tf_utils.get_optimizer_lr_metric(optimizer)
    if lr_metric:
        metrics.append(lr_metric)

    model.compile(optimizer, loss_fn, metrics=metrics)
    tf_utils.print_model_info(model)

    # load checkpointed weights before the pruning
    if hasattr(exp, 'load_model_before_pruning') and exp.load_model_before_pruning:
        model.load_weights(exp.load_model_before_pruning)
        print(f"LOADED BEFORE PRUNING {exp.load_model_before_pruning}")

    model = pruning_utils.set_pruning_masks(model=model,
                                            pruning_method=exp.pruning,
                                            pruning_config=exp.pruning_config,
                                            dataset=dataset)
    assert isinstance(model, tf.keras.Model)

    # load or reset weights after the pruning, do not change masks
    if hasattr(exp, 'load_model_after_pruning') and exp.load_model_after_pruning:
        if exp.load_model_after_pruning == 'random':
            ckp = None
        else:
            ckp = exp.load_model_after_pruning
        num_masks = tf_utils.reset_weights_to_checkpoint(model,
                                                         ckp=ckp,
                                                         skip_keyword='kernel_mask')
        print(f"LOADED AFTER PRUNING {exp.load_model_after_pruning}, but keeping "
              f"{num_masks} masks")

    if hasattr(exp, 'load_optimizer') and exp.load_optimizer:
        tf_utils.build_optimizer(model, optimizer)
        tf_utils.update_optimizer(optimizer, exp.load_optimizer)
        print(f"LOADED OPTIMIZER {exp.load_optimizer}")

    checkpoint_callback = tf_utils.CheckpointAfterEpoch(epoch2path=exp.save_model,
                                                        epoch2path_optim=exp.save_optim)

    # just apply pruning by zeroing weights with previously calculated masks
    pruning_utils.apply_pruning_masks(model, pruning_method=exp.pruning)
    steps_per_epoch = min(exp.steps, exp.steps_per_epoch)
    num_epochs = int(exp.steps / steps_per_epoch)

    if hasattr(exp, 'initial_epoch'):
        initial_epoch = exp.initial_epoch
    else:
        initial_epoch = 0

    if hasattr(exp, 'get_unused_parameters'):
        if unused := exp.get_unused_parameters():
            print("!!!ATTENTION!!! Unused parameters:")
            print(unused)

    checkpoint_callback.set_model(model)
    checkpoint_callback.on_epoch_end(epoch=-1)  # for checkpointing before training

    if num_epochs > initial_epoch:
        history = model.fit(x=dataset['train'],
                            validation_data=dataset['valid'],
                            steps_per_epoch=steps_per_epoch,
                            epochs=num_epochs,
                            initial_epoch=initial_epoch,
                            callbacks=[checkpoint_callback])
        exp.FINAL_DENSITY = pruning_utils.report_density(model)
        print("FINAL DENSITY:", exp.FINAL_DENSITY)
        tf_utils.log_from_history(history.history, exp=exp)
    checkpoint_callback.list_created_checkpoints()


if __name__ == '__main__':
    class exp:
        name = 'temp'
        precision = 16
        save_model = {}
        save_optim = {}
        tensorboard_log = None
        steps = 200
        steps_per_epoch = 20
        dataset = 'cifar10'
        optimizer = 'tf.optimizers.SGD'
        pruning = 'magnitude'
        model = 'lenet'
        dataset_config = {'train_batch_size': 128, 'valid_batch_size': 512}
        optimizer_config = {'learning_rate': 0.1, 'momentum': 0.9}
        pruning_config = {'sparsity': 0.5}
        model_config = {'input_shape': [32, 32, 3], 'n_classes': 10, 'l2_reg': 1e-5}


    main(exp)
