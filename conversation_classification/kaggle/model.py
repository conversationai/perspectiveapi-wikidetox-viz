"""
A basic Bag of Words classifier for the Toxic Comment Classification Kaggle
challenge, https://www.kaggle.com/c/jigsaw-toxic-comment-classification-challenge

To Run:

python model.py --train_data=train.csv --predict_data=test.csv --y_class=toxic

Output:
  * writes predictions on heldout test data to TEST_OUT_PATH
  * writes predictions on unlabled predict data to PREDICT_OUT_PATH
"""

import argparse
import sys

import pandas as pd
import tensorflow as tf
import numpy as np
import sklearn as sk
from sklearn.model_selection import train_test_split

FLAGS = None

# Data Params
MAX_LABEL = 2
Y_CLASSES = ['toxic', 'severe_toxic','obscene','threat','insult','identity_hate']
DATA_SEED = 48173 # Random seed used for splitting the data into train/test
TRAIN_PERCENT = .8 # Percent of data to allocate to training
MAX_DOCUMENT_LENGTH = 500 # Max length of each comment in words

# Model Params
EMBEDDING_SIZE = 50 # Size of learned  word embedding
WORDS_FEATURE = 'words' # Name of the input words feature.
MODEL_LIST = ['bag_of_words']

# Training Params
TRAIN_SEED = 9812 # Random seed used to initialize training
TRAIN_STEPS = 1000 # Number of steps to take while training
LEARNING_RATE = 0.01
BATCH_SIZE = 120

# Output Params
TEST_OUT_PATH = 'test_out.csv' # Where to write results on heldout data
PREDICT_OUT_PATH = 'predict_out.csv' # Where to write results on unlabled data

class WikiData:

  def __init__(self, path):
    self.data = self._load_data(path)
    self.data['comment_text'] = self.data['comment_text'].astype(str)

  def _load_data(self, path):
      df =  pd.read_csv(path)

      return df

  def split(self, train_percent, y_class, seed):
    """
    Split divides the Wikipedia data into test and train subsets.

    Args:
      * train_percent (float): the fraction of data to use for training
      * y_class (string): the attribute of the wiki data to predict, e.g. 'toxic'
      * seed (integer): a seed to use to split the data in a reproducible way

    Returns:
      x_train (dataframe): the comment_text for the training data
      y_train (dataframe): the 0 or 1 labels for the training data
      x_test (dataframe):  the comment_text for the test data
      y_test (dataframe):  the 0 or 1 labels for the test data
    """

    if y_class not in Y_CLASSES:
      tf.logging.error('Specified y_class {0} not in list of possible classes {1}'\
            .format(y_class, Y_CLASSES))
      raise ValueError

    if train_percent >= 1 or train_percent <= 0:
      tf.logging.error('Specified train_percent {0} is not between 0 and 1'\
            .format(train_percent))
      raise ValueError

    tf.logging.info("Training on class: '{}'".format(y_class))
    tf.logging.info("Training data split: {}".format(train_percent))

    X = self.data['comment_text']
    y = self.data[y_class]
    x_train, x_test, y_train, y_test = train_test_split(
      X, y, test_size=1-train_percent, random_state=seed)

    return x_train, x_test, y_train, y_test

def estimator_spec_for_softmax_classification(logits, labels, mode):
  """
  Depending on the value of mode, different EstimatorSpec arguments are required.

  For mode == ModeKeys.TRAIN: required fields are loss and train_op.
  For mode == ModeKeys.EVAL: required field is loss.
  For mode == ModeKeys.PREDICT: required fields are predictions.

  Returns EstimatorSpec instance for softmax classification.
  """
  predicted_classes = tf.argmax(logits, axis=1)
  predictions = {
    'classes': predicted_classes,

    # Add softmax_tensor to the graph. It is used for PREDICT.
    'probs': tf.nn.softmax(logits, name='softmax_tensor')
  }

  # PREDICT Mode
  if mode == tf.estimator.ModeKeys.PREDICT:
    return tf.estimator.EstimatorSpec(mode=mode, predictions=predictions)

  # Calculate loss for both TRAIN and EVAL modes
  loss = tf.losses.sparse_softmax_cross_entropy(labels=labels, logits=logits)

  # TRAIN Mode
  if mode == tf.estimator.ModeKeys.TRAIN:
    optimizer = tf.train.AdamOptimizer(learning_rate=LEARNING_RATE)
    train_op = optimizer.minimize(loss, global_step=tf.train.get_global_step())
    logging_hook = tf.train.LoggingTensorHook(tensors={'loss': loss}, every_n_iter=20)

    return tf.estimator.EstimatorSpec(
      mode=mode,
      loss=loss,
      train_op=train_op,
      training_hooks=[logging_hook],
      predictions={'loss': loss}
    )

  # EVAL Mode
  eval_metric_ops = {
    'accuracy': tf.metrics.accuracy(labels=labels, predictions=predicted_classes)
  }
  return tf.estimator.EstimatorSpec(
    mode=mode, loss=loss, eval_metric_ops=eval_metric_ops)

def bag_of_words_model(features, labels, mode):
  """
  A bag-of-words model using a learned word embedding. Note it disregards the
  word order in the text.

  Returns a tf.estimator.EstimatorSpec.
  """

  bow_column = tf.feature_column.categorical_column_with_identity(
      WORDS_FEATURE, num_buckets=n_words)

  # The embedding values are initialized randomly, and are trained along with
  # all other model parameters to minimize the training loss.
  bow_embedding_column = tf.feature_column.embedding_column(
      bow_column, dimension=EMBEDDING_SIZE)

  bow = tf.feature_column.input_layer(
      features,
      feature_columns=[bow_embedding_column])

  logits = tf.layers.dense(bow, MAX_LABEL, activation=None)

  return estimator_spec_for_softmax_classification(
      logits=logits, labels=labels, mode=mode)

def main():
    global n_words

    tf.logging.set_verbosity(tf.logging.INFO)

    if FLAGS.verbose:
      tf.logging.info('Running in verbose mode')
      tf.logging.set_verbosity(tf.logging.DEBUG)

    # Load and split data
    tf.logging.debug('Loading data {}'.format(FLAGS.train_data))
    data = WikiData(FLAGS.train_data)

    x_train_text, x_test_text, y_train, y_test \
      = data.split(TRAIN_PERCENT, FLAGS.y_class, DATA_SEED)

    # Process data
    vocab_processor = tf.contrib.learn.preprocessing.VocabularyProcessor(
      MAX_DOCUMENT_LENGTH)

    x_train = np.array(list(vocab_processor.fit_transform(x_train_text)))
    x_test = np.array(list(vocab_processor.fit_transform(x_test_text)))
    y_train = np.array(y_train)
    y_test = np.array(y_test)

    n_words = len(vocab_processor.vocabulary_)
    tf.logging.info('Total words: %d' % n_words)

    # Build model
    if FLAGS.model == 'bag_of_words':
      model_fn = bag_of_words_model

      # Subtract 1 because VocabularyProcessor outputs a word-id matrix where word
      # ids start from 1 and 0 means 'no word'. But categorical_column_with_identity
      # assumes 0-based count and uses -1 for missing word.
      x_train -= 1
      x_test -= 1
    else:
      tf.logging.error("Unknown specified model '{}', must be one of {}"
                       .format(FLAGS.model, MODEL_LIST))
      raise ValueError

    classifier = tf.estimator.Estimator(
      model_fn=model_fn,
      config=tf.contrib.learn.RunConfig(
        tf_random_seed=TRAIN_SEED,
      ),
      model_dir=None)

    # Train model
    train_input_fn = tf.estimator.inputs.numpy_input_fn(
      x={WORDS_FEATURE: x_train},
      y=y_train,
      batch_size=BATCH_SIZE,
      num_epochs=None, # Note: For training, set this to None, so the input_fn
                       # keeps returning data until the required number of train
                       # steps is reached.
      shuffle=True)

    classifier.train(input_fn=train_input_fn, steps=TRAIN_STEPS)

    # Predict on held-out test data
    test_input_fn = tf.estimator.inputs.numpy_input_fn(
      x={WORDS_FEATURE: x_test},
      y=y_test,
      num_epochs=1,     # Note: For evaluation and prediction set this to 1,
                        # so the input_fn will iterate over the data once and
                        # then raise OutOfRangeError
      shuffle=False)

    predicted_test = classifier.predict(input_fn=test_input_fn)
    test_out = pd.DataFrame(
      [(p['classes'], p['probs'][1]) for p in predicted_test],
      columns=['y_predicted', 'prob']
    )
    test_out['comment_text'] = x_train_text
    test_out['y_true'] = y_test

    # Write out predictions and probabilities for test data
    tf.logging.info("Writing test predictions to {}".format(TEST_OUT_PATH))
    test_out.to_csv(TEST_OUT_PATH)

    # Score with sklearn and TensorFlow (hopefully they're the same!)
    sklearn_score = sk.metrics.accuracy_score(y_test, test_out['y_predicted'])
    tf_scores = classifier.evaluate(input_fn=test_input_fn)

    tf.logging.info('')
    tf.logging.info('----------Evaluation on Held-Out Data---------')
    tf.logging.info('Accuracy (sklearn)\t: {0:f}'.format(sklearn_score))
    tf.logging.info('Accuracy (tensorflow)\t: {0:f}'.format(tf_scores['accuracy']))
    tf.logging.info('')

    # If specified, predict on unlabeled data
    if FLAGS.predict_data is None:
      return

    data_unlabeled = WikiData(FLAGS.predict_data).data

    tf.logging.info('Generating predictions for {0} unlabeled examples in {1}'
                    .format(len(data_unlabeled), FLAGS.predict_data))

    x_unlabeled = np.array(list(
      vocab_processor.fit_transform(data_unlabeled['comment_text'])))

    unlabled_input_fn = tf.estimator.inputs.numpy_input_fn(
      x={WORDS_FEATURE: x_unlabeled},
      num_epochs=1,
      shuffle=False)

    predicted_unlabeled = classifier.predict(input_fn=unlabled_input_fn)
    unlabeled_out = pd.DataFrame(
      [(p['classes'], p['probs'][1]) for p in predicted_unlabeled],
      columns=['y_pred', 'prob']
    )
    unlabeled_out['comment_text'] = data_unlabeled['comment_text']

    # Write out predictions and probabilities for unlabled "predict" data
    tf.logging.info("Writing predictions to {}".format(PREDICT_OUT_PATH))
    unlabeled_out.to_csv(PREDICT_OUT_PATH)

if __name__ == '__main__':

  parser = argparse.ArgumentParser()
  parser.add_argument(
      '--verbose', help='Run in verbose mode.', action='store_true')
  parser.add_argument(
      "--train_data", type=str, default="", help="Path to the training data.")
  parser.add_argument(
      "--predict_data", type=str, default="", help="Path to the prediction data.")
  parser.add_argument(
      "--y_class", type=str, default="toxic",
    help="Class to train model against, one of {}".format(Y_CLASSES))
  parser.add_argument(
      "--model", type=str, default="bag_of_words",
    help="The model to train, one of {}".format(MODEL_LIST))

  FLAGS, unparsed = parser.parse_known_args()

  main()
