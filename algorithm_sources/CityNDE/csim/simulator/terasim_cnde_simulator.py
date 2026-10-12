from __future__ import annotations

__all__ = ["build_nnde_simulator"]

import os
import sys
import pickle

import numpy as np
import random
from matplotlib import pyplot as plt
import torch
import tqdm
import math
from typing import Iterable, Literal

import copy
import sys

from cnde.models.model import MotionTransformer
from cnde.config import cfg as origin_cfg, cfg_from_list, cfg_from_yaml_file, log_config_to_file
from .simulator import RouteTLSimulator
from ..controller import RuleEnhancedController

def build_nnde_simulator(map_path: str, desc: str = "terasim-test"):
    cfg_file = "/home/ubuntu/lishu/CityNDE_/assets/model_cfg.yaml"
    ckpt_file = "/home/ubuntu/lishu/CityNDE_/assets/nn_weights.pth"

    cfg = cfg_from_yaml_file(cfg_file, origin_cfg)
    model = MotionTransformer(config=cfg.MODEL)
    checkpoint = torch.load(ckpt_file, map_location='cpu')
    model.load_state_dict(checkpoint['model_state'], strict=True)
    model.eval().requires_grad_(False)

    controller = RuleEnhancedController(core=model, control_step=5, control_resolution=0.1, sample_strategy='argmax-u')

    simulator = RouteTLSimulator(map_path=map_path,
                                 sim_resolution=0.1,
                                 history_step=11,
                                 auto_agent_dep=False,
                                 auto_agent_arr=False,
                                 agent_controller=controller)
    
    simulator.desc = desc
    
    controller.map_enhance = simulator.map
    controller.agent_enhance = simulator.agent_record
    
    simulator.reset()
    
    return simulator


    







