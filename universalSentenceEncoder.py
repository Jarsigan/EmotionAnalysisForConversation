# Please use python 3.5 or above

import tensorflow as tf
import tensorflow_hub as hub
# import matplotlib.pyplot as plt
# import pandas as pd
# import seaborn as sns

import argparse
import io
import json
import os
import re

import numpy as np
from keras import optimizers
from keras.layers import Input, Dense, Embedding, LSTM, Concatenate, Reshape, Bidirectional, Conv1D, GlobalMaxPooling1D, \
    GlobalAveragePooling1D, Dropout
from keras.models import Model
from keras.preprocessing.sequence import pad_sequences
from keras.preprocessing.text import Tokenizer
from keras.utils import to_categorical

# Path to training and testing data file. This data can be downloaded from a link, details of which will be provided.
from tensorflow.python.estimator import keras

trainDataPath = ""
testDataPath = ""
# Output file that will be generated. This file can be directly submitted.
solutionPath = ""
# Path to directory where GloVe file is saved.
gloveDir = ""
endPath = ""

NUM_FOLDS = None  # Value of K in K-fold Cross Validation
NUM_CLASSES = None  # Number of classes - Happy, Sad, Angry, Others
MAX_NB_WORDS = None  # To set the upper limit on the number of tokens extracted using keras.preprocessing.text.Tokenizer
MAX_SEQUENCE_LENGTH = None  # All sentences having lesser number of words than this will be padded
EMBEDDING_DIM = None  # The dimension of the word embeddings
BATCH_SIZE = None  # The batch size to be chosen for training the model.
LSTM_DIM = None  # The dimension of the representations learnt by the LSTM model
DROPOUT = None  # Fraction of the units to drop for the linear transformation of the inputs. Ref - https://keras.io/layers/recurrent/
NUM_EPOCHS = None  # Number of epochs to train a model for

label2emotion = {0: "others", 1: "happy", 2: "sad", 3: "angry"}
emotion2label = {"others": 0, "happy": 1, "sad": 2, "angry": 3}


def preprocessData(dataFilePath, mode):
    """Load data from a file, process and return indices, conversations and labels in separate lists
    Input:
        dataFilePath : Path to train/test file to be processed
        mode : "train" mode returns labels. "test" mode doesn't return labels.
    Output:
        indices : Unique conversation ID list
        conversations : List of 3 turn conversations, processed and each turn separated by the <eos> tag
        labels : [Only available in "train" mode] List of labels
    """
    indices = []
    conversations = []
    labels = []
    u1 = []
    u2 = []
    u3 = []
    with io.open(dataFilePath, encoding="utf8") as finput:
        finput.readline()
        for line in finput:
            # Convert multiple instances of . ? ! , to single instance
            # okay...sure -> okay . sure
            # okay???sure -> okay ? sure
            # Add whitespace around such punctuation
            # okay!sure -> okay ! sure
            repeatedChars = ['.', '?', '!', ',']
            for c in repeatedChars:
                lineSplit = line.split(c)
                while True:
                    try:
                        lineSplit.remove('')
                    except:
                        break
                cSpace = ' ' + c + ' '
                line = cSpace.join(lineSplit)

            line = line.strip().split('\t')
            if mode == "train":
                # Train data contains id, 3 turns and label
                label = emotion2label[line[4]]
                labels.append(label)

            conv = ' <eos> '.join(line[1:4])

            u1.append(line[1])
            u2.append(line[2])
            u3.append(line[3])

            # Remove any duplicate spaces
            duplicateSpacePattern = re.compile(r'\ +')
            conv = re.sub(duplicateSpacePattern, ' ', conv)

            indices.append(int(line[0]))
            conversations.append(conv.lower())

    if mode == "train":
        return indices, conversations, labels, u1, u2, u3
    else:
        return indices, conversations, u1, u2, u3


def getMetrics(predictions, ground):
    """Given predicted labels and the respective ground truth labels, display some metrics
    Input: shape [# of samples, NUM_CLASSES]
        predictions : Model output. Every row has 4 decimal values, with the highest belonging to the predicted class
        ground : Ground truth labels, converted to one-hot encodings. A sample belonging to Happy class will be [0, 1, 0, 0]
    Output:
        accuracy : Average accuracy
        microPrecision : Precision calculated on a micro level. Ref - https://datascience.stackexchange.com/questions/15989/micro-average-vs-macro-average-performance-in-a-multiclass-classification-settin/16001
        microRecall : Recall calculated on a micro level
        microF1 : Harmonic mean of microPrecision and microRecall. Higher value implies better classification
    """
    # [0.1, 0.3 , 0.2, 0.1] -> [0, 1, 0, 0]

    discretePredictions = to_categorical(predictions.argmax(axis=1))

    truePositives = np.sum(discretePredictions * ground, axis=0)
    falsePositives = np.sum(np.clip(discretePredictions - ground, 0, 1), axis=0)
    falseNegatives = np.sum(np.clip(ground - discretePredictions, 0, 1), axis=0)

    print("True Positives per class : ", truePositives)
    print("False Positives per class : ", falsePositives)
    print("False Negatives per class : ", falseNegatives)

    # ------------- Macro level calculation ---------------
    macroPrecision = 0
    macroRecall = 0
    # We ignore the "Others" class during the calculation of Precision, Recall and F1
    for c in range(1, NUM_CLASSES):
        precision = truePositives[c] / (truePositives[c] + falsePositives[c])
        macroPrecision += precision
        recall = truePositives[c] / (truePositives[c] + falseNegatives[c])
        macroRecall += recall
        f1 = (2 * recall * precision) / (precision + recall) if (precision + recall) > 0 else 0
        print("Class %s : Precision : %.3f, Recall : %.3f, F1 : %.3f" % (label2emotion[c], precision, recall, f1))

    macroPrecision /= 3
    macroRecall /= 3
    macroF1 = (2 * macroRecall * macroPrecision) / (macroPrecision + macroRecall) if (
                                                                                                 macroPrecision + macroRecall) > 0 else 0
    print("Ignoring the Others class, Macro Precision : %.4f, Macro Recall : %.4f, Macro F1 : %.4f" % (
    macroPrecision, macroRecall, macroF1))

    # ------------- Micro level calculation ---------------
    truePositives = truePositives[1:].sum()
    falsePositives = falsePositives[1:].sum()
    falseNegatives = falseNegatives[1:].sum()

    print(
        "Ignoring the Others class, Micro TP : %d, FP : %d, FN : %d" % (truePositives, falsePositives, falseNegatives))

    microPrecision = truePositives / (truePositives + falsePositives)
    microRecall = truePositives / (truePositives + falseNegatives)

    microF1 = (2 * microRecall * microPrecision) / (microPrecision + microRecall) if (
                                                                                                 microPrecision + microRecall) > 0 else 0
    # -----------------------------------------------------

    predictions = predictions.argmax(axis=1)
    ground = ground.argmax(axis=1)
    accuracy = np.mean(predictions == ground)

    print("Accuracy : %.4f, Micro Precision : %.4f, Micro Recall : %.4f, Micro F1 : %.4f" % (
    accuracy, microPrecision, microRecall, microF1))
    return accuracy, microPrecision, microRecall, microF1


def writeNormalisedData(dataFilePath, texts):
    """Write normalised data to a file
    Input:
        dataFilePath : Path to original train/test file that has been processed
        texts : List containing the normalised 3 turn conversations, separated by the <eos> tag.
    """
    normalisedDataFilePath = dataFilePath.replace(".txt", "_normalised.txt")
    with io.open(normalisedDataFilePath, 'w', encoding='utf8') as fout:
        with io.open(dataFilePath, encoding='utf8') as fin:
            fin.readline()
            for lineNum, line in enumerate(fin):
                line = line.strip().split('\t')
                normalisedLine = texts[lineNum].strip().split('<eos>')
                fout.write(line[0] + '\t')
                # Write the original turn, followed by the normalised version of the same turn
                fout.write(line[1] + '\t' + normalisedLine[0] + '\t')
                fout.write(line[2] + '\t' + normalisedLine[1] + '\t')
                fout.write(line[3] + '\t' + normalisedLine[2] + '\t')
                try:
                    # If label information available (train time)
                    fout.write(line[4] + '\n')
                except:
                    # If label information not available (test time)
                    fout.write('\n')


def getEmbeddingMatrix(wordIndex):
    """Populate an embedding matrix using a word-index. If the word "happy" has an index 19,
       the 19th row in the embedding matrix should contain the embedding vector for the word "happy".
    Input:
        wordIndex : A dictionary of (word : index) pairs, extracted using a tokeniser
    Output:
        embeddingMatrix : A matrix where every row has 100 dimensional GloVe embedding
    """
    embeddingsIndex = {}
    # Load the embedding vectors from ther GloVe file
    with io.open(os.path.join(gloveDir, 'glove.840B.300d.txt'), encoding="utf8") as f:
        for line in f:
            values = line.split(' ')
            # print(values)
            word = values[0]
            embeddingVector = np.array([float(val) for val in values[1:]])
            embeddingsIndex[word] = embeddingVector

    print('Found %s word vectors.' % len(embeddingsIndex))

    # Minimum word index of any word is 1.
    embeddingMatrix = np.zeros((len(wordIndex) + 1, EMBEDDING_DIM))
    for word, i in wordIndex.items():
        embeddingVector = embeddingsIndex.get(word)
        if embeddingVector is not None:
            # words not found in embedding index will be all-zeros.
            embeddingMatrix[i] = embeddingVector

    return embeddingMatrix


def buildModel(embeddingMatrix):
    """Constructs the architecture of the model
    Input:
        embeddingMatrix : The embedding matrix to be loaded in the embedding layer.
    Output:
        model : A basic LSTM model
    """
    x1 = Input(shape=(100,), dtype='int32', name='main_input1')
    x2 = Input(shape=(100,), dtype='int32', name='main_input2')
    x3 = Input(shape=(100,), dtype='int32', name='main_input3')

    print("x1 %s " % x1)

    embeddingLayer = Embedding(embeddingMatrix.shape[0],
                               EMBEDDING_DIM,
                               weights=[embeddingMatrix],
                               input_length=MAX_SEQUENCE_LENGTH,
                               trainable=False)
    emb1 = embeddingLayer(x1)
    emb2 = embeddingLayer(x2)
    emb3 = embeddingLayer(x3)

    # print(len(emb1[0]))
    print(emb1[0])

    lstm = Bidirectional(LSTM(LSTM_DIM, dropout=DROPOUT))

    lstm1 = lstm(emb1)
    lstm2 = lstm(emb2)
    lstm3 = lstm(emb3)

    inp = Concatenate(axis=-1)([lstm1, lstm2, lstm3])

    inp = Reshape((3, 2 * LSTM_DIM,))(inp)

    lstm_up = LSTM(LSTM_DIM, dropout=DROPOUT)

    out = lstm_up(inp)

    out = Dense(NUM_CLASSES, activation='softmax')(out)

    adam = optimizers.adam(lr=LEARNING_RATE)
    model = Model([x1, x2, x3], out)
    model.compile(loss='categorical_crossentropy',
                  optimizer=adam,
                  metrics=['acc'])
    print(model.summary())

    return model


def buildModelNew():
    """Constructs the architecture of the model
    Input:
        embeddingMatrix : The embedding matrix to be loaded in the embedding layer.
    Output:
        model : A basic LSTM model
    """

    # Convolution parameters
    nb_filter = 150
    cnn_activation = 'relu'

    kernel_size = 3
    pooling = 'max'
    dropout = None

    x1 = Input(shape=(512,), dtype='float32', name='main_input1')
    x2 = Input(shape=(512,), dtype='float32', name='main_input2')
    x3 = Input(shape=(512,), dtype='float32', name='main_input3')

    print("x1 %s " % x1)

    # lstm = Bidirectional(LSTM(LSTM_DIM, dropout=DROPOUT))
    print(x1.shape)

    inp = Concatenate(axis=-1)([x1, x2, x3])
    print(inp.shape)

    inp = Reshape((1, LSTM_DIM,))(inp)

    lstm_up = LSTM(LSTM_DIM, dropout=DROPOUT)

    out = lstm_up(inp)

    p1 = []
    c0 = Conv1D(nb_filter, kernel_size, padding='valid', activation=cnn_activation, strides=1)(out)
    p0 = {'max': GlobalMaxPooling1D()(c0), 'avg': GlobalAveragePooling1D()(c0)}.get(pooling, c0)
    p1.append(p0)

    if len(p1) > 1:
        opt = keras.layers.concatenate(p1, axis=1)
    else:
        opt = p1[0]

    if dropout is not None:
        d0 = Dropout(dropout)
        opt = d0(opt)


    out = Dense(NUM_CLASSES, activation='softmax')(opt)

    adam = optimizers.adam(lr=LEARNING_RATE)
    model = Model([x1, x2, x3], out)
    model.compile(loss='categorical_crossentropy',
                  optimizer=adam,
                  metrics=['acc'])
    print(model.summary())

    return model


def main():
    parser = argparse.ArgumentParser(description="Baseline Script for SemEval")
    parser.add_argument('-config', help='Config to read details', required=True)
    args = parser.parse_args()

    with open(args.config) as configfile:
        config = json.load(configfile)

    global trainDataPath, testDataPath, solutionPath, endPath
    global NUM_FOLDS, NUM_CLASSES, MAX_NB_WORDS, MAX_SEQUENCE_LENGTH, EMBEDDING_DIM
    global BATCH_SIZE, LSTM_DIM, DROPOUT, NUM_EPOCHS, LEARNING_RATE

    trainDataPath = config["train_data_path"]
    testDataPath = config["test_data_path"]
    solutionPath = config["solution_path"]
    endPath = config["end_path"]

    NUM_FOLDS = config["num_folds"]
    NUM_CLASSES = config["num_classes"]
    MAX_NB_WORDS = config["max_nb_words"]
    MAX_SEQUENCE_LENGTH = config["max_sequence_length"]
    EMBEDDING_DIM = config["embedding_dim"]
    BATCH_SIZE = config["batch_size"]
    LSTM_DIM = config["lstm_dim"]
    DROPOUT = config["dropout"]
    LEARNING_RATE = config["learning_rate"]
    NUM_EPOCHS = config["num_epochs"]

    print("Processing training data...")
    trainIndices, trainTexts, labels, u1_train, u2_train, u3_train = preprocessData(trainDataPath, mode="train")



    # Write normalised text to file to check if normalisation works. Disabled now. Uncomment following line to enable
    # writeNormalisedData(trainDataPath, trainTexts)
    print("Processing test data...")
    testIndices, testTexts, u1_test, u2_test, u3_test = preprocessData(testDataPath, mode="test")
    # writeNormalisedData(testDataPath, testTexts)

    # np.random.shuffle(trainIndices)

    # u1_train = u1_train[trainIndices]
    # u2_train = u2_train[trainIndices]
    # u3_train = u3_train[trainIndices]

    print("Found %s u1 train." % u1_train[0])
    print("Found %s labels." % labels[0])
    trainData = [u1_train, u2_train, u3_train]
    testData = [u1_test, u2_test, u3_test]

    trainEmbeddingList = []
    testEmbeddingList = []
    module_url = "https://tfhub.dev/google/universal-sentence-encoder-large/3" # @param ["https://tfhub.dev/google/universal-sentence-encoder/2", "https://tfhub.dev/google/universal-sentence-encoder-large/3"]

    # Import the Universal Sentence Encoder's TF Hub module
    embed = hub.Module(module_url)

    # Compute a representation for each message, showing various lengths supported.
    word = "Elephant"
    sentence = "I am a sentence for which I would like to get its embedding."
    paragraph = (
        "Universal Sentence Encoder embeddings also support short paragraphs. "
        "There is no hard limit on how   long the paragraph is. Roughly, the longer "
        "the more 'diluted' the embedding will be.")
    messages = [word, sentence, paragraph]

    # Reduce logging output.
    tf.logging.set_verbosity(tf.logging.ERROR)

    with tf.Session() as session:
        session.run([tf.global_variables_initializer(), tf.tables_initializer()])
        for utturance in trainData:
            message_embeddings = session.run(embed(utturance))
            uttEmb = []
            for i, message_embedding in enumerate(np.array(message_embeddings).tolist()):
                # print("Message: {}".format(messages[i]))
                # print("Embedding size: {}".format(len(message_embedding)))
                uttEmb.append(message_embedding)
                # message_embedding_snippet = ", ".join(
                #     (str(x) for x in message_embedding))
                # print("Embedding: [{}, ...]\n".format(message_embedding_snippet))
            trainEmbeddingList.append(uttEmb)
            # uttEmb.clear()

            # test data
            for utturance in testData:
                message_embeddings = session.run(embed(utturance))
                uttEmb = []
                for i, message_embedding in enumerate(np.array(message_embeddings).tolist()):
                    # print("Message: {}".format(messages[i]))
                    # print("Embedding size: {}".format(len(message_embedding)))
                    uttEmb.append(message_embedding)
                    # message_embedding_snippet = ", ".join(
                    #     (str(x) for x in message_embedding))
                    # print("Embedding: [{}, ...]\n".format(message_embedding_snippet))
                testEmbeddingList.append(uttEmb)
                # uttEmb.clear()

    #########################################################################

    # Randomize data
    u1_data = trainEmbeddingList[0]
    u2_data = trainEmbeddingList[1]
    u3_data = trainEmbeddingList[2]
    print(len(u1_data[0]))
    labels = to_categorical(np.asarray(labels))
    print("Found %s labels len." % len(labels[0]))
    # print(labels[0])
    print("Shape of label tensor: ", labels.shape)
    # np.random.shuffle(trainIndices)

    # u1_data = u1_data[trainIndices]
    # u2_data = u2_data[trainIndices]
    # u3_data = u3_data[trainIndices]

    print("trainIndices %s len." % len(trainIndices))
    print("train indices %s ." % trainIndices)

    # print("u1_data %s len." % len(u1_data[0]))
    # print("u1 data %s." % u1_data[0])
    # print(u1_data)
    # print(u2_data)
    # print(u3_data)

    # labels = labels[trainIndices]
    # print(labels)
    # Perform k-fold cross validation
    metrics = {"accuracy": [],
               "microPrecision": [],
               "microRecall": [],
               "microF1": []}

    print("Starting k-fold cross validation...")
    print('-' * 40)
    print("Building model...")
    print("\n======================================")

    print("Retraining model on entire data to create solution file")
    # model = buildModel(embeddingMatrix)

    model = buildModelNew()
    model.fit([u1_data, u2_data, u3_data], labels, epochs=NUM_EPOCHS, batch_size=BATCH_SIZE)
    model.save('EP%d_LR%de-5_LDim%d_BS%d.h5' % (NUM_EPOCHS, int(LEARNING_RATE * (10 ** 5)), LSTM_DIM, BATCH_SIZE))
    # model = load_model('EP%d_LR%de-5_LDim%d_BS%d.h5'%(NUM_EPOCHS, int(LEARNING_RATE*(10**5)), LSTM_DIM, BATCH_SIZE))

    print("Creating solution file...")
    # u1_testData, u2_testData, u3_testData = pad_sequences(u1_testSequences, maxlen=MAX_SEQUENCE_LENGTH), pad_sequences(u2_testSequences, maxlen=MAX_SEQUENCE_LENGTH), pad_sequences(u3_testSequences, maxlen=MAX_SEQUENCE_LENGTH)

    predictions = model.predict([testEmbeddingList[0], testEmbeddingList[1], testEmbeddingList[2]],
                                batch_size=BATCH_SIZE)
    predictions = predictions.argmax(axis=1)

    with io.open(solutionPath, "w", encoding="utf8") as fout:
        fout.write('\t'.join(["id", "turn1", "turn2", "turn3", "label"]) + '\n')
        with io.open(testDataPath, encoding="utf8") as fin:
            fin.readline()
            for lineNum, line in enumerate(fin):
                fout.write('\t'.join(line.strip().split('\t')[:4]) + '\t')
                fout.write(label2emotion[predictions[lineNum]] + '\n')
    print("Completed. Model parameters: ")
    print("Learning rate : %.3f, LSTM Dim : %d, Dropout : %.3f, Batch_size : %d"
          % (LEARNING_RATE, LSTM_DIM, DROPOUT, BATCH_SIZE))

    print("Calculating F1 value")
    solIndices, solTexts, sollabels, u1_sol, u2_sol, u3_sol = preprocessData(endPath, mode="train")
    sollabels = to_categorical(np.asarray(sollabels))

    endIndices, endTexts, endlabels, u1_end, u2_end, u3_end = preprocessData(solutionPath, mode="train")
    endlabels = to_categorical(np.asarray(endlabels))

    # predictions = model.predict(xVal, batch_size=BATCH_SIZE)
    accuracy, microPrecision, microRecall, microF1 = getMetrics(endlabels, sollabels)
    metrics["accuracy"].append(accuracy)
    metrics["microPrecision"].append(microPrecision)
    metrics["microRecall"].append(microRecall)
    metrics["microF1"].append(microF1)

    print("\n============= Metrics =================")
    print("Average Cross-Validation Accuracy : %.4f" % (sum(metrics["accuracy"]) / len(metrics["accuracy"])))
    print("Average Cross-Validation Micro Precision : %.4f" % (
            sum(metrics["microPrecision"]) / len(metrics["microPrecision"])))
    print("Average Cross-Validation Micro Recall : %.4f" % (sum(metrics["microRecall"]) / len(metrics["microRecall"])))
    print("Average Cross-Validation Micro F1 : %.4f" % (sum(metrics["microF1"]) / len(metrics["microF1"])))


if __name__ == '__main__':
    main()

