import robustml

print(robustml.__file__)
from robustml_model import InputTransformations
import sys
import argparse
import tensorflow as tf
import numpy as np
from helpers import *
import cv2
import time

npop = 300     # population size
sigma = 0.1    # noise standard deviation
alpha = 0.05  # learning rate
# alpha = 0.001  # learning rate
boxmin = 0
boxmax = 1
boxplus = (boxmin + boxmax) / 2.
boxmul = (boxmax - boxmin) / 2.
folder = './liclipadvImages/'
l2thresh = 0.05 * np.sqrt(299*299)

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--imagenet-path', type=str, default='../../obfuscated_zoo/imagenet_val',
            help='path to the test_batch file from http://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz')
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--end', type=int, default=100)
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    test_loss = 0
    correct = 0
    total = 0
    totalImages = 0
    succImages = 0
    faillist = []



    # set up TensorFlow session
    config = tf.ConfigProto()
    config.gpu_options.allow_growth=True
    sess = tf.Session(config=config)


    # initialize a model
    defense = 'jpeg'  # 'bitdepth | jpeg | crop | quilt | tv' ############# change ##############################
    model = InputTransformations(sess,defense)

    # initialize an attack (it's a white box attack, and it's allowed to look
    # at the internals of the model in any way it wants)
    # attack = BPDA(sess, model, epsilon=model.threat_model.epsilon, debug=args.debug)
    # attack = Attack(sess, model.model, epsilon=model.threat_model.epsilon)

    # initialize a data provider for CIFAR-10 images
    provider = robustml.provider.ImageNet(args.imagenet_path, model.dataset.shape)
    start = 62
    end = 120
    total = 0
    l2_avg = []

    for i in range(start, end):
        success = False
        print('evaluating %d of [%d, %d)' % (i, start, end), file=sys.stderr)

        inputs, targets= provider[i]
        modify = np.random.randn(1,3,32,32) * 0.001
        ##### thermometer encoding
        
        logits = model.outlogits(inputs.reshape(1,299,299,3))
        # print(logits)
        if np.argmax(logits) != targets:
            print('skip the wrong example ', i)
            continue
        totalImages += 1

        for runstep in range(400):
            step_start = time.time()
            Nsample = np.random.randn(npop, 3,32,32)
            
            modify_try = modify.repeat(npop,0) + sigma*Nsample
            temp = []
            resize_start =time.time()
            for x in modify_try:
                temp.append(cv2.resize(x.transpose(1,2,0), dsize=(299,299), interpolation=cv2.INTER_LINEAR).transpose(2,0,1))
            modify_try = np.array(temp)
#             print('resize time ', time.time()-resize_start,flush=True)
            input_start = time.time()

            inputimg = inputs.transpose(2,0,1)+modify_try
            if runstep % 10 == 0:
                temp = []
                for x in modify:
                    temp.append(cv2.resize(x.transpose(1,2,0), dsize=(299,299), interpolation=cv2.INTER_LINEAR).transpose(2,0,1))
                modify_test = np.array(temp)
                
                realinputimg = inputs.transpose(2,0,1)+modify_test
                realinputimg = np.clip(realinputimg,0,1)
                
                realdist = realinputimg - inputs.transpose(2,0,1)
                reall2dist = np.sum((realinputimg - inputs.transpose(2,0,1))**2)**0.5
                if reall2dist > l2thresh:
                    realdist = realdist * (l2thresh/reall2dist)

                realclipdist = realdist

                realclipinput = realclipdist + inputs.transpose(2,0,1)

                l2real =  np.sum((realclipinput - inputs.transpose(2,0,1))**2)**0.5

                #l2real =  np.abs(realclipinput - inputs.numpy())
                logits = model.outlogits(realclipinput.transpose(0,2,3,1))
                outputsreal = logits

                print('logits ',np.sort(outputsreal[0])[-1:-6:-1])
                print('target label ', np.argsort(outputsreal[0])[-1:-6:-1])
                print('negative_logits ', np.sort(outputsreal[0])[0:3:1])
                print('l2real: '+str(l2real))
                sys.stdout.flush()
                # print(outputsreal)
                if (l2real > l2thresh+0.0001):
                    break
                if (np.argmax(outputsreal[0]) != targets) and (l2real <= l2thresh):
                    succImages += 1
                    success = True
                    print('clipimage succImages: '+str(succImages)+'  totalImages: '+str(totalImages))

                    l2_avg.append(l2real.max())
#                     imsave(folder+classes[targets[0]]+'_'+str("%06d" % batch_idx)+'.jpg',inputs.transpose(1,2,0))
                    break
                
                      
            dist = inputimg - inputs.transpose(2,0,1)
#             l2dist = np.mean(np.square(inputimg - (np.tanh(newimg) * boxmul + boxplus)).reshape(npop,-1), axis = 1)**0.5
            l2dist = np.sum(np.square(inputimg - inputs.transpose(2,0,1)).reshape(npop,-1), axis = 1)**0.5
            dist = dist * ((l2thresh/l2dist).reshape(npop,1,1,1))
            clipinput = (dist + inputs.transpose(2,0,1)).reshape(npop,3,299,299)
            clipinput = np.clip(clipinput,0,1)
            
#             newNsample = torch_arctanh((clipinput-boxplus) / boxmul)
            
            

            
            target_onehot =  np.zeros((1,1000))
            target_onehot[0][targets]=1.
#             print('input_time : ', time.time()-input_start,flush=True)
            classify_start = time.time()
            logits = model.outlogits(clipinput.transpose(0,2,3,1))
            outputs = logits
#             print('classify_time : ', time.time()-classify_start,flush=True)

            target_onehot = target_onehot.repeat(npop,0)



            real = (target_onehot * outputs).sum(1)
            other = ((1. - target_onehot) * outputs - target_onehot * 10000.).max(1)[0]

            loss1 = np.clip(real - other, 0.,1000)

            Reward = 0.5 * loss1 
#             Reward = l2dist

            Reward = -Reward

            A = (Reward - np.mean(Reward)) / (np.std(Reward)+1e-7)

            
            modify = modify + (alpha/(npop*sigma)) * ((np.dot(Nsample.reshape(npop,-1).T, A)).reshape(3,32,32))
#             print('one step time : ', time.time()-step_start)
        if not success:
            faillist.append(i)
    print(faillist)
    success_rate = succImages/float(totalImages)
    print('l2 average : ', np.mean(l2_avg))



    print('attack success rate: %.2f%% (over %d data points)' % (success_rate*100, args.end-args.start))

if __name__ == '__main__':
    main()
