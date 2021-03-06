import CNN
from text_cnn import TextCNN
import data_helpers
import os
import numpy as np
import time
import tensorflow as tf
import datetime

with tf.Graph().as_default():
    start_time = time.time()
    session_conf = tf.ConfigProto(allow_soft_placement=CNN.FLAGS.allow_soft_placement,
        log_device_placement=CNN.FLAGS.log_device_placement)
    sess = tf.Session(config=session_conf)
    with sess.as_default():
        cnn = TextCNN(filter_sizes=list(map(int, CNN.FLAGS.filter_sizes.split(","))),
            num_filters=CNN.FLAGS.num_filters, vec_shape=(CNN.FLAGS.sequence_length, CNN.FLAGS.embedding_size * CNN.FLAGS.window_size + 2 * CNN.FLAGS.distance_dim),
            l2_reg_lambda=CNN.FLAGS.l2_reg_lambda)
        # Define Training procedure
        global_step = tf.Variable(0, name="global_step", trainable=False)
        optimizer = tf.train.AdamOptimizer(1e-3)
        grads_and_vars = optimizer.compute_gradients(cnn.loss)
        train_op = optimizer.apply_gradients(grads_and_vars, global_step=global_step)

        # Keep track of gradient values and sparsity (optional)
        grad_summaries = []
        for g, v in grads_and_vars:
            if g is not None:
                grad_hist_summary = tf.histogram_summary("{}/grad/hist".format(v.name), g)
                sparsity_summary = tf.scalar_summary("{}/grad/sparsity".format(v.name), tf.nn.zero_fraction(g))
                grad_summaries.append(grad_hist_summary)
                grad_summaries.append(sparsity_summary)
        grad_summaries_merged = tf.merge_summary(grad_summaries)

        # Output directory for models and summaries
        timestamp = str(int(time.time()))
        out_dir = os.path.abspath(os.path.join(os.path.curdir, "data", timestamp))
        print("Writing to {}\n".format(out_dir))

        # Summaries for loss and accuracy
        loss_summary = tf.scalar_summary("loss", cnn.loss)
        acc_summary = tf.scalar_summary("accuracy", cnn.accuracy)

        # Train Summaries
        train_summary_op = tf.constant(1)
        train_summary_op = tf.merge_summary([loss_summary, acc_summary, grad_summaries_merged])
        train_summary_dir = os.path.join(out_dir, "summaries", "train")
        train_summary_writer = tf.train.SummaryWriter(train_summary_dir, sess.graph)

        # Dev summaries
        dev_summary_op = tf.merge_summary([loss_summary, acc_summary])
        dev_summary_dir = os.path.join(out_dir, "summaries", "dev")
        dev_summary_writer = tf.train.SummaryWriter(dev_summary_dir, sess.graph)

        # Checkpoint directory. Tensorflow assumes this directory already exists so we need to create it
        checkpoint_dir = os.path.abspath(os.path.join(out_dir, "checkpoints"))
        checkpoint_prefix = os.path.join(checkpoint_dir, "model")
        if not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir)
        saver = tf.train.Saver(tf.all_variables())

        # Initialize all variables
        sess.run(tf.global_variables_initializer())


        def train_step(x_text_train, y_batch):
            feed_dict = {
                cnn.input_x: x_text_train,
                cnn.input_y: y_batch,
                cnn.dropout_keep_prob: CNN.FLAGS.dropout_keep_prob
            }
            _, step, summaries, loss, accuracy, scores = sess.run(
                [train_op, global_step, train_summary_op, cnn.loss, cnn.accuracy, cnn.scores],
                feed_dict)
            time_str = datetime.datetime.now().isoformat()
            print("{}: step {}, loss {:g}, acc {:g}".format(time_str, step, loss, accuracy))
            train_summary_writer.add_summary(summaries, step)


        def dev_step(x_text_dev, y_batch, writer=None):
            """
            Evaluates model on a dev set
            """
            feed_dict = {
                cnn.input_x: x_text_dev,
                cnn.input_y: y_batch,
                cnn.dropout_keep_prob: 1.0
            }
            step, loss, accuracy = sess.run(
                [global_step, cnn.loss, cnn.accuracy],
                feed_dict)
            time_str = datetime.datetime.now().isoformat()
            print("{}: step {}, loss {:g}, acc {:g}".format(time_str, step, loss, accuracy))
            return loss, accuracy
            # if writer:
            #     writer.add_summary(summaries, step)

        batch_iter = CNN.get_batches()
        for batch in batch_iter:
            loss = accuracy = 0.0
            X_train, y_train = zip(*batch)
            X_train, y_train = np.asarray(X_train), np.asarray(y_train)
            n_times_val = int(X_train.shape[0]) / int(CNN.FLAGS.K)
            print(X_train.shape)
            for k in range(CNN.FLAGS.K):
                X_val = X_train[k * n_times_val:(k + 1) * n_times_val][:][:]
                Y_val = y_train[k * n_times_val:(k + 1) * n_times_val][:]
                X = X_train[0: k * n_times_val][:][:]
                X = np.concatenate((X, X_train[(k + 1) * n_times_val:][:][:]), 0)
                Y = y_train[0: k * n_times_val][:]
                Y = np.concatenate((Y, y_train[(k + 1) * n_times_val:][:]), 0)
                # print(X.shape, Y.shape, X_val.shape, Y_val.shape)
                train_step(X, Y)
                current_step = tf.train.global_step(sess, global_step)
                print("Evaluation:")
                l, a = dev_step(np.asarray(X_val), np.asarray(Y_val))
                loss += l
                accuracy += a
                print("")
                if current_step % CNN.FLAGS.checkpoint_every == 0:
                    path = saver.save(sess, checkpoint_prefix, global_step=current_step)
                    print("Saved model checkpoint to {}\n".format(path))
            print(np.sum(loss), np.sum(accuracy))
            loss = float(loss) / 4.0
            accuracy = float(accuracy) / 4.0
            print("{}-Fold results".format(CNN.FLAGS.K))
            print("Loss = %f, Accuracy = %f" %(loss, accuracy))
            print("-------------------")
        print("Finished in time %0.3f" % (time.time() - start_time))