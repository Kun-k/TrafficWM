import argparse
import sys
import os

import numpy as np
import torch
from cnde.config import cfg as origin_cfg, cfg_from_yaml_file
from cnde.models.model import MotionTransformer
from csim.controller import RuleEnhancedController
from csim.simulator.interactive_simulator import InteractiveRouteTLSimulator
from cutils import setup_seed

os.environ["CUDA_VISIBLE_DEVICES"] = "2"


def main():
    parser = argparse.ArgumentParser(description="CityNDE Interactive Simulator")
    parser.add_argument("--map_path", type=str, default="assets/map/map_nuplan_boston_5type_segments_rebuild.pkl", 
                        help="Path to map .pkl file")
    parser.add_argument("--total_step", type=int, default=10000, help="Max simulation steps")
    parser.add_argument("--init_mode", type=str, default="random_tl_only",
                        choices=["random", "empty", "data", "data_random_tl", "random_tl_only", "none"])
    parser.add_argument("--no_vis", action="store_true", help="Disable visualization")
    parser.add_argument("--viewer_mode", type=str, default="region_full", choices=["overview", "region", "region_full"])
    parser.add_argument("--region_center", type=float, default=np.array([357, -1217], dtype=np.float64), help="Viewer region center np.array([x, y])")
    parser.add_argument("--save_file", type=str, default="output/scenario_debug_test.pkl",
                        help="Path to save scenario record")
    parser.add_argument("--image_size", type=int, default=16384, help="Viewer image size (pixels)")
    parser.add_argument("--render_interval", type=int, default=1, help="Render every N simulation steps")
    parser.add_argument("--sync_render", action="store_true", help="Disable async rendering and render in simulation thread")
    parser.add_argument("--pause_interval", type=int, default=0,
                        help="Auto-pause every N steps (0=only manual pause)")
    parser.add_argument("--port", type=int, default=8890, help="HTTP port for web viewer")
    parser.add_argument("--default_spawn_speed", type=float, default=2.0, help="Default speed for moving vehicles spawned via UI click")
    parser.add_argument("--cfg_file", type=str, default="assets/config/model_cfg.yaml")
    parser.add_argument("--ckpt_file", type=str, default="assets/ckpt/nn_weights.pth")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    
    setup_seed(args.seed)
    
    cfg = cfg_from_yaml_file(args.cfg_file, origin_cfg)
    model = MotionTransformer(config=cfg.MODEL)
    checkpoint = torch.load(args.ckpt_file, map_location='cpu', weights_only=True)
    model.load_state_dict(checkpoint['model_state'], strict=True)
    model.eval().requires_grad_(False)
    
    controller = RuleEnhancedController(core=model, control_step=5, control_resolution=0.1)
    
    simulator = InteractiveRouteTLSimulator(
        map_path=args.map_path,
        sim_resolution=0.1,
        history_step=11,
        agent_controller=controller,
        visualize=not args.no_vis,
        viewer_mode=args.viewer_mode,
        region_center=args.region_center,
        image_size=args.image_size,
        render_interval=args.render_interval,
        async_render=not args.sync_render,
        pause_interval=args.pause_interval,
        port=args.port,
        default_spawn_speed=args.default_spawn_speed,
    )
    
    controller.map_enhance = simulator.map
    controller.agent_enhance = simulator.agent_record

    simulator.run(
        init_mode=args.init_mode,
        total_step=args.total_step,
        save_file=args.save_file,
    )


if __name__ == "__main__":
    main()