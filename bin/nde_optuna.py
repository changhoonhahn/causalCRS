''' 

script for training a large number of flows using the Optuna hyperparameter
optimization framework. 

'''
import os,sys
import numpy as np
import astropy.table as aTable

import torch
from torch import nn 
from torch.utils.tensorboard.writer import SummaryWriter

import optuna 
from sbi import utils as Ut
from sbi import inference as Inference

##################################################################################
cuda = torch.cuda.is_available()
device = ("cuda:0" if cuda else "cpu")
##################################################################################

treat_or_control = sys.argv[1]
nf_model = sys.argv[2]

# read in training data 
if treat_or_control == 'treat': 
    train_data = np.load('../dat/fema_crs.treat.train.npy')
elif treat_or_control == 'control': 
    train_data = np.load('../dat/fema_crs.control.train.npy')
else: 
    raise ValueError

##################################################################################
# prior 
lower_bounds = torch.tensor([1])
upper_bounds = torch.tensor([9])

prior = Ut.BoxUniform(low=lower_bounds, high=upper_bounds, device=device)

##################################################################################
# OPTUNA
##################################################################################
# Optuna Parameters
n_trials    = 1000
study_name  = '%s.v2.%s' % (treat_or_control, nf_model)

output_dir = '../dat/nde'

n_jobs     = 1
if not os.path.isdir(os.path.join(output_dir, study_name)): 
    os.system('mkdir %s' % os.path.join(output_dir, study_name))
storage    = 'sqlite:///%s/%s/%s.db' % (output_dir, study_name, study_name)
n_startup_trials = 20

n_blocks_min, n_blocks_max = 2, 5 
n_transf_min, n_transf_max = 2, 5 
n_hidden_min, n_hidden_max = 32, 128 
n_lr_min, n_lr_max = 5e-6, 1e-3 


def Objective(trial):
    ''' bojective function for optuna 
    '''
    # Generate the model                                         
    n_blocks = trial.suggest_int("n_blocks", n_blocks_min, n_blocks_max)
    n_transf = trial.suggest_int("n_transf", n_transf_min,  n_transf_max)
    n_hidden = trial.suggest_int("n_hidden", n_hidden_min, n_hidden_max, log=True)
    lr = trial.suggest_float("lr", n_lr_min, n_lr_max, log=True) 
    if nf_model == 'made': 
        n_comp = trial.suggest_int("n_comp", 2, 20, log=True)
        neural_posterior = Ut.posterior_nn(nf_model, 
                hidden_features=n_hidden, 
                num_transforms=n_transf, 
                num_blocks=n_blocks, 
                num_mixture_components=n_comp, 
                use_batch_norm=True)

    else: 
        neural_posterior = Ut.posterior_nn(nf_model, 
                hidden_features=n_hidden, 
                num_transforms=n_transf, 
                num_blocks=n_blocks, 
                use_batch_norm=True)

    anpe = Inference.SNPE(prior=prior,
            density_estimator=neural_posterior,
            device=device, 
            summary_writer=SummaryWriter('%s/%s/%s.%i' % 
                (output_dir, study_name, study_name, trial.number)))

    anpe.append_simulations( 
            torch.tensor(train_data[:,:1], dtype=torch.float32).to(device), 
            torch.tensor(train_data[:,1:], dtype=torch.float32).to(device))

    p_theta_x_est = anpe.train(
            training_batch_size=50,
            learning_rate=lr, 
            show_train_summary=True)

    # save trained NPE  
    qphi    = anpe.build_posterior(p_theta_x_est)
    fqphi   = os.path.join(output_dir, study_name, '%s.%i.pt' % (study_name, trial.number))
    torch.save(qphi, fqphi)

    best_valid_log_prob = anpe._summary['best_validation_log_prob'][0]

    return -1*best_valid_log_prob

sampler     = optuna.samplers.TPESampler(n_startup_trials=n_startup_trials) 
study       = optuna.create_study(study_name=study_name, sampler=sampler, storage=storage, directions=["minimize"], load_if_exists=True) 

study.optimize(Objective, n_trials=n_trials, n_jobs=n_jobs)
print("  Number of finished trials: %i" % len(study.trials))
