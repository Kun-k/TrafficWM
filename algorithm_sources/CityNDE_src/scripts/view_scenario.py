import os
import pickle
import numpy as np
from csim.viewer import ScenarioViewer

if __name__ == "__main__":
    viewer = ScenarioViewer(scenario_file="/mnt/4TB/rk/CityNDE_UI/output/scenario_debug_test.pkl")
    viewer.make_agent_centric_video(video_desc="debug", 
                                    output_dir="/mnt/4TB/rk/CityNDE_UI/output/tmp_videos",
                                    ego_num=50)
    viewer.make_region_centric_video(video_desc="debug", 
                                     output_dir="/mnt/4TB/rk/CityNDE_UI/output/tmp_videos")
    
# if __name__ == "__main__":
#     viewer = ScenarioViewer(scenario_file="/mnt/4TB/rk/output/scenario_debug_test")
#     # viewer.make_agent_centric_video(video_desc="debug", 
#     #                                 output_dir="output/boston_10000steps_new",
#     #                                 # ego_num=5,
#     #                                 ego_id=[1021],
#     #                                 step_range=(1900, 2200),
#     #                                 plot_id=True,
#     #                                 )
#     with open('output/lane_closure_980_resume_2.pkl', 'rb') as f:
#         data = pickle.load(f)
#     center = data["map"]["polyline"][75645]["states"][-1][:2]
#     # def last_pos(vehicle_id):
#     #     for vids, states in list(zip(data["vehicle_id_per_step"], data["vehicle_state_per_step"]))[::-1]:
#     #         for vid, state in zip(vids, states):
#     #             if vid == vehicle_id:
#     #                 center = state[:2]
#     #                 return center
#     #     raise ValueError(f"Vehicle ID {vehicle_id} not found in the scenario.")
#     # center = last_pos(709)
#     viewer.make_region_centric_video(video_desc="sg", 
#                                      output_dir="output/tmp_videos",
#                                     #  step_range=(0, 3200),
#                                     #  region_center=center,
#                                     #  plot_id=True,
#                                     #  region_center=np.array([275, -267])
#                                      )
#     # viewer.make_region_centric_video_lane_closure(video_desc="lc", 
#     #                                               output_dir="output/tmp_videos",
#     #                                             #   step_range=(0, 5600),
#     #                                               region_center=center,
#     #                                                 lc_polygon=[np.array([
#     #                                                     [-440.71860233, 353.56796544],
#     #                                                     [-421.99033512, 336.39898726],
#     #                                                     [-430, 339.9],
#     #                                                     [-437.96214822, 347.1],
#     #                                                     ])],
#     #                                               lc_step_range=(950, 2560),
#     # )
#     # viewer.make_region_photo_lane_closure(photo_desc="lc",
#     #                                      output_dir="output/tmp_photos",
#     #                                      region_center=center,
#     #                                      steps=[400, 2550, 5520],
#     #                                      lc_polygon=[np.array([
#     #                                          [-440.71860233, 353.56796544],
#     #                                          [-421.99033512, 336.39898726],
#     #                                          [-430, 339.9],
#     #                                          [-437.96214822, 347.1],
#     #                                          ])],
#     #                                      lc_step_range=(950, 2560),
#     #                                      plot_step=True,
#     # )
#     # viewer.make_region_photo(photo_desc="debug",
#     #                         output_dir="output/tmp_photos",
#     #                         region_center=center,
#     #                         # region_center=np.array([357, -1217]),
#     #                         steps=[14080],
#     #                         # plot_id=True,
#     #                         )
#     # viewer.make_region_photo(photo_desc="debug",
#     #                          output_dir="output/boston_10000steps_new",
#     #                          region_center=center,
#     #                          step=22000,
#     #                          plot_id=False,
#     # )
#     # viewer.make_overview_video(video_desc="debug", 
#     #                            output_dir="output/tmp_videos",
#     #                            video_frame_interval=10,
#     #                            )
#     # viewer.make_grid_video(video_desc="debug", 
#     #                        output_dir="output/boston_10000steps_new",
#     #                     #    ego_id=[9024, 8762, 9122, 9037, 8639]
#     #                        )