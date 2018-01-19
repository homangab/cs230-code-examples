"""Create the input data pipeline using `tf.data`"""

import tensorflow as tf


def load_dataset_from_text(path_txt, vocab=None):
    """Create tf.data Instance from txt file

    Args:
        path_txt: (string) path containing one example per line
        vocab: (tf.lookuptable)
    """
    # Load txt file containing tokens
    dataset = tf.data.TextLineDataset(path_txt)

    # Convert line into list of tokens
    dataset = dataset.map(lambda string: tf.string_split([string]).values)

    # Load vocabularies into lookup table string -> int (word or tag -> id)
    if vocab is not None:
        dataset = dataset.map(lambda tokens: vocab.lookup(tokens))

    return dataset


def input_fn(is_training, sentences, tags=None, batch_size=5, pad_word='<pad>', pad_tag='O'):
    """Input function for NER

    Args:
        is_training: (bool) whether to use the train or test pipeline.
                     At training, we shuffle the data and have multiple epochs
        path_sentences: (string) path to file containing the sentences
        path_tags: (string) path to file containing the tags
        batch_size: (int) number of element in a batch

    """
    # TODO: num_parallel_calls ?
    # TODO: unknown words

    # Zip the sentence and the tags together
    if tags is not None:
        dataset = tf.data.Dataset.zip((sentences, tags))
    else:
        dataset = sentences

    # Load all the dataset in memory for shuffling is training
    buffer_size = 100 if is_training else 1

    # Create batches and pad the sentences of different length
    if tags is not None:
        padded_shapes = (tf.TensorShape([None]),  # sentence of unknown size
                         tf.TensorShape([None]))  # tags of unknown size
    else:
        padded_shapes = tf.TensorShape([None])  # sentence of unknown size

    if tags is not None:
        padding_values = (pad_word,    # sentence padded on the right with word_pad
                          pad_tag)     # tags padded on the right with tag_pad
    else:
        padding_values = (pad_word)    # sentence padded on the right with word_pad


    dataset = (dataset
        .padded_batch(batch_size, padded_shapes=padded_shapes, padding_values=padding_values)
        .shuffle(buffer_size=buffer_size)
        .prefetch(1)  # make sure you always have one batch ready to serve
    )

    iterator = dataset.make_initializable_iterator()

    if tags is not None:
        (sentence, tags) = iterator.get_next()
        init_op = iterator.initializer

        inputs = {
            'sentence': sentence,
            'tags': tags,
            'iterator_init_op': init_op
        }
    else:
        sentence = iterator.get_next()
        init_op = tf.group(*[tf.tables_initializer(), iterator.initializer])

        inputs = {
            'sentence': sentence,
            'iterator_init_op': init_op
        }

    return inputs
