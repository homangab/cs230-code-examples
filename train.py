"""Train the model"""

import argparse
import json
import logging
import os

import numpy as np
import tensorflow as tf
from tensorflow.examples.tutorials.mnist import input_data
from tqdm import trange

from input_data import input_fn
from input_data import load_dataset_from_text
from model.utils import Params
from model.utils import set_logger
from model.utils import save_dict_to_json
from model.model import model_fn
from evaluate import evaluate


parser = argparse.ArgumentParser()
parser.add_argument('--model_dir', default='experiments/test')
parser.add_argument('--restore_dir', default=None)


def train(sess, model_spec, params, num_steps, writer):
    """Train the model on `num_steps` batches

    Args:
        sess: (tf.Session) current session
        model_spec: (dict) contains the graph operations or nodes needed for training
        params: (Params) hyperparameters
        num_steps: (int) train for this number of batches
        writer: (tf.summary.FileWriter) writer for summaries
    """
    # Get relevant graph operations or nodes needed for training
    loss = model_spec['loss']
    train_op = model_spec['train_op']
    update_metrics = model_spec['update_metrics']
    metrics = model_spec['metrics']
    summary_op = model_spec['summary_op']
    global_step = tf.train.get_global_step()

    # Load the training dataset into the pipeline and initialize the metrics local variables
    sess.run(model_spec['iterator_init_op'])
    sess.run(model_spec['metrics_init_op'])

    # Use tqdm for progress bar
    t = trange(num_steps)
    for i in t:
        # Evaluate summaries for tensorboard only once in a while
        if i % params.save_summary_steps == 0:
            # Perform a mini-batch update
            _, _, loss_val, summ, global_step_val = sess.run([train_op, update_metrics, loss,
                                                              summary_op, global_step])
            # Write summaries for tensorboard
            writer.add_summary(summ, global_step_val)
        else:
            _, _, loss_val = sess.run([train_op, update_metrics, loss])
        # Log the loss in the tqdm progress bar
        t.set_postfix(loss='{:05.3f}'.format(loss_val))


    metrics_values = {k: v[0] for k, v in metrics.items()}
    metrics_val = sess.run(metrics_values)
    metrics_string = " ; ".join("{}: {:05.3f}".format(k, v) for k, v in metrics_val.items())
    logging.info("- Train metrics: " + metrics_string)


def train_and_evaluate(train_model_spec, eval_model_spec, model_dir, params, restore_dir=None):
    """Train the model and evaluate every epoch.

    Args:
        train_model_spec: (dict) contains the graph operations or nodes needed for training
        eval_model_spec: (dict) contains the graph operations or nodes needed for evaluation
        model_dir: (string) directory containing config, weights and log
        params: (Params) contains hyperparameters of the model.
                Must define: num_epochs, train_size, batch_size, eval_size, save_summary_steps
    """
    # initialize tf.Saver instances to save weights during training
    last_saver = tf.train.Saver() # will keep last 5 epochs
    best_saver = tf.train.Saver(max_to_keep=1)  # only keep 1 best checkpoint (best on eval)

    with tf.Session() as sess:
        # reload weights from directory if specified
        if restore_dir is not None:
            logging.info("Restoring parameters from {}".format(restore_dir))
            save_path = tf.train.latest_checkpoint(restore_dir)
            last_saver.restore(sess, save_path)

        # For tensorboard (takes care of writing summaries to files)
        train_writer = tf.summary.FileWriter(os.path.join(model_dir, 'train_summaries'), sess.graph)
        eval_writer = tf.summary.FileWriter(os.path.join(model_dir, 'eval_summaries'), sess.graph)

        # Initialize model variables
        sess.run(train_model_spec['variable_init_op'])
        sess.run(tf.tables_initializer()) # initialize the lookup tables

        best_eval_acc = 0.0
        for epoch in range(params.num_epochs):
            # Run one epoch
            logging.info("Epoch {}/{}".format(epoch + 1, params.num_epochs))
            # compute number of batches in one epoch (one full pass over the training set)
            num_steps = (params.train_size + 1) // params.batch_size
            train(sess, train_model_spec, params, num_steps, train_writer)

            # Save weights
            last_save_path = os.path.join(model_dir, 'last_weights', 'after-epoch')
            last_saver.save(sess, last_save_path, global_step=epoch + 1)

            # Evaluate for one epoch on validation set
            num_steps = (params.eval_size + 1) // params.batch_size
            metrics = evaluate(sess, eval_model_spec, num_steps, eval_writer)

            # If best_eval, best_save_path
            eval_acc = metrics['accuracy']
            if eval_acc >= best_eval_acc:
                # Store new best accuracy
                best_eval_acc = eval_acc
                # Save weights
                best_save_path = os.path.join(model_dir, 'best_weights', 'after-epoch')
                best_save_path = best_saver.save(sess, best_save_path, global_step=epoch + 1)
                logging.info("- Found new best accuracy, saving in {}".format(best_save_path))
                # Save best eval metrics in a json file in the model directory
                best_json_path = os.path.join(model_dir, "metrics_eval_best_weights.json")
                save_dict_to_json(metrics, best_json_path)

            # Save latest eval metrics in a json file in the model directory
            last_json_path = os.path.join(model_dir, "metrics_eval_last_weights.json")
            save_dict_to_json(metrics, last_json_path)


if __name__ == '__main__':
    # Set the random seed for the whole graph for reproductible experiments
    tf.set_random_seed(230)

    # Load the parameters from json file
    args = parser.parse_args()
    json_path = os.path.join(args.model_dir, 'params.json')
    assert os.path.isfile(json_path), "No json configuration file found at {}".format(json_path)
    params = Params(json_path)

    # Set the logger
    set_logger(os.path.join(args.model_dir, 'train.log'))

    # Load Vocabularies
    path_vocab_words = 'data/NER/words.txt'
    path_vocab_tags = 'data/NER/tags.txt'
    vocab_words = tf.contrib.lookup.index_table_from_file(path_vocab_words, num_oov_buckets=1)
    vocab_tags = tf.contrib.lookup.index_table_from_file(path_vocab_tags)
    id_pad_word = vocab_words.lookup(tf.constant('<pad>'))
    id_pad_tag = vocab_tags.lookup(tf.constant('O'))

    # Create the input data pipeline
    logging.info("Creating the datasets...")
    train_sentences = load_dataset_from_text('data/NER/train/sentences.txt', vocab_words)
    train_tags = load_dataset_from_text('data/NER/train/tags.txt', vocab_tags)
    test_sentences = load_dataset_from_text('data/NER/test/sentences.txt', vocab_words)
    test_tags = load_dataset_from_text('data/NER/test/tags.txt', vocab_tags)

    # specify the train and eval datasets size
    params.update('data/NER/dataset_params.json')
    params.eval_size = params.test_size
    params.vocab_size += 1 # to account for unknown words

    # Create the two iterators over the two datasets
    train_inputs = input_fn(True, train_sentences, train_tags, pad_word=id_pad_word,
                            pad_tag=id_pad_tag)
    eval_inputs = input_fn(False, test_sentences, test_tags, pad_word=id_pad_word,
                            pad_tag=id_pad_tag)
    logging.info("- done.")

    # Define the model
    logging.info("Creating the model...")
    train_model_spec = model_fn(True, train_inputs, params)
    eval_model_spec = model_fn(False, eval_inputs, params, reuse=True)
    logging.info("- done.")

    # Train the model
    logging.info("Starting training for {} epoch(s)".format(params.num_epochs))
    train_and_evaluate(train_model_spec, eval_model_spec, args.model_dir, params, args.restore_dir)
