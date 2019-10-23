import torch
# from discard.separate_model import LowerLayers, UpperLayer
from discard.separate_model import  UpperLayer
from utils import *
import time
import argparse
import os

# from DDPG_PopArt.sac_v2_my_TCN_critic_bn_V2_popart import device
# from sac_v2_my_TCN_critic_bn_V2_popart import device

torch.cuda.current_device()
torch.cuda._initialized = True

device = 'cuda' if torch.cuda.is_available() else 'cpu'
# device = 'cpu'


def RMSELoss(yhat, y):
    return torch.sqrt(torch.mean((yhat-y)**2))


class PopArt(torch.nn.Module):
# class PopArt:
    def __init__(self, mode, LowerLayers, n_in, H, n_out, lr, beta=None):
        super(PopArt, self).__init__()
        self.mode = mode.upper()
        assert self.mode in ['SGD', 'ART', 'POPART'], "Please select mode from 'SGD', 'Art' or 'PopArt'."
        self.lower_layers = LowerLayers
        self.upper_layer  = UpperLayer(H, n_out).to(device)
        self.sigma = torch.tensor(1., dtype=torch.float)  # consider scalar first
        self.sigma_new = None
        self.mu = torch.tensor(0., dtype=torch.float)
        self.mu_new = None
        self.nu = self.sigma**2 + self.mu**2 # second-order moment
        self.beta = beta
        self.lr = lr
        self.loss_func = torch.nn.MSELoss()
        self.loss = None
        # self.opt_lower = torch.optim.SGD(self.lower_layers.parameters(), self.lr)
        self.opt_upper = torch.optim.SGD(self.upper_layer.parameters(), self.lr)


    def art(self, y):
        self.mu_new = (1. - self.beta) * self.mu + self.beta * y.mean()
        self.nu = (1. - self.beta) * self.nu + self.beta * (y**2).mean()
        self.sigma_new = torch.sqrt(self.nu - self.mu_new**2)
        

    def pop(self):
        relative_sigma = (self.sigma / self.sigma_new)
        self.upper_layer.output_linear.weight.data.mul_(relative_sigma)
        self.upper_layer.output_linear.bias.data.mul_(relative_sigma).add_((self.mu-self.mu_new)/self.sigma_new)

    def update_stats(self):
        # update statistics
        if self.sigma_new is not None:
            self.sigma = self.sigma_new
        if self.mu_new is not None:
            self.mu = self.mu_new

    def normalize(self, y):
        return (y - self.mu) / self.sigma

    def denormalize(self, y):
        return self.sigma * y + self.mu

    def backward(self):
        # self.opt_lower.zero_grad()
        self.opt_upper.zero_grad()
        self.loss.backward(retain_graph=True)
        # self.loss.backward()

    def step(self):
        # self.opt_lower.step()
        self.opt_upper.step()

    # def forward(self, x, y):
    #     if self.mode in ['POPART', 'ART']:
    #         self.art(y)
    #     if self.mode in ['POPART']:
    #         self.pop()
    #     self.update_stats()
    #     y_pred = self.upper_layer(self.lower_layers(x))
    #     self.loss = 0.5 * self.loss_func(y_pred, self.normalize(y))

    #     self.backward()
    #     self.step()

    #     return self.loss

    def forward(self, x, u, y):
        if self.mode in ['POPART', 'ART']:
            self.art(y)
        if self.mode in ['POPART']:
            self.pop()
        self.update_stats()
        y_pred = self.upper_layer(self.lower_layers(x, u))

        self.loss = 0.5 * self.loss_func(y_pred, self.normalize(y))
        # self.loss = 0.5 * self.loss_func(y_pred.float(), self.normalize(y).float())
        # self.loss = torch.tensor(self.loss, dtype=torch.float, requires_grad = True) 
        # .clone().detach()
        self.loss = self.loss.clone().detach().requires_grad_(True)
        self.backward()
        self.step()
        # print('#########')
        # input()
        # print('Q_loss.: {}, y_pred.: {} , y: {}'.format( self.loss, y_pred, y))
        
        # print(self.upper_layer.output_linear.weight)
        # print(self.upper_layer.output_linear.bias)
        # input()
        # print('$$$$$',self.loss)
        # input()
        return self.loss , self.lower_layers 

    def output(self, x, u):

        return self.upper_layer(self.lower_layers(x, u))



    # def training_model(self, X, Y):
    #     rmse = []
    #     for i in range(len(X)):
    #         # load one sample per step
    #         input = torch.tensor(X[i], dtype=torch.float)
    #         output = torch.tensor([Y[i]], dtype=torch.float)

    #         # predict output with current model
    #         pred = self.forward(input, output)

    #         # record rmse
    #         with torch.no_grad():
    #             rmse.append(RMSELoss(self.denormalize(pred), output).item())

    #         # one-step training
    #         self.backward()
    #         self.step()

    #     return moving_average(rmse)


# parser settings
parser = argparse.ArgumentParser()
parser.add_argument('-l', '--lr', default=-3.5,
                    help="learning rate, default: 10^-3.5")
parser.add_argument('-b', '--beta', default=None,
                    help="moving average coefficient, default: None")
parser.add_argument('-m', '--mode', type=str, default='SGD',
                    help="agent mode, default: SGD, one of ['SGD', 'ART', 'PopArt']")


if __name__ == "__main__":

    args = parser.parse_args()
    lr = pow(10., float(args.lr))
    # beta = pow(10., float(args.beta))
    beta = None
    mode = args.mode

    rmses = []
    for seed in range(50):
        print("Running for seed {:d}.".format(seed))
        start_tic = time.time()
        # build network
        torch.manual_seed(seed)
        # NOTE: multiple learning rate with 0.5 to mimic the 0.5*MSE
        agent = PopArt(mode, 16, 10, 1, lr, beta)

        # generate dataset
        os.system("python dataset_generator.py -s {seed:d}".format(seed=seed))

        # load dataset
        with open('dataset/dataset-with-weired-value.pkl', 'rb') as f:
            x = pickle.load(f)
            y = pickle.load(f)

        print('x: {}, y: {}  '.format(x, y ))
        # print('x: {}, y: {} , xshape: {} , yshape: {}'.format(x, y , x.shape(), y.shape())
        print('xshape: {} , yshape: {}'.format( x.shape, y.shape))
      

        rmse = agent.training_model(x, y)
        rmses.append(rmse)
        print("Time elapsed {:.2f} seconds for run {:d}.".format(time.time()-start_tic, seed))

    samples = np.linspace(0, 4995, 4995, dtype=int)
    m, l, u = median_and_percentile(rmses, axis=0)

    # save results
    save_results('{mode:s}_lr={lr:s}_beta={beta:s}.pkl'.format(mode=mode, lr=args.lr, beta=args.beta),
                 samples, m, l, u)