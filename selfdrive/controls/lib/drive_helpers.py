import math
import numpy as np

from cereal import car, log, custom
from openpilot.common.conversions import Conversions as CV
from openpilot.common.numpy_fast import clip, interp
from openpilot.common.realtime import DT_MDL, DT_CTRL
from openpilot.selfdrive.modeld.constants import ModelConstants

# WARNING: this value was determined based on the model's training distribution,
#          model predictions above this speed can be unpredictable
# V_CRUISE's are in kph
V_CRUISE_MIN = 8
V_CRUISE_MAX = 161
V_CRUISE_UNSET = 255
V_CRUISE_INITIAL = 40
V_CRUISE_INITIAL_EXPERIMENTAL_MODE = 105
IMPERIAL_INCREMENT = CV.MPH_TO_KPH  # Exact 1.609344 conversion

MIN_SPEED = 1.0
CONTROL_N = 17
CAR_ROTATION_RADIUS = 0.0

# EU guidelines
MAX_LATERAL_JERK = 5.0
MAX_VEL_ERR = 5.0

ButtonEvent = car.CarState.ButtonEvent
ButtonType = car.CarState.ButtonEvent.Type
CRUISE_LONG_PRESS = 50
CRUISE_NEAREST_FUNC = {
  ButtonType.accelCruise: math.ceil,
  ButtonType.decelCruise: math.floor,
}
CRUISE_INTERVAL_SIGN = {
  ButtonType.accelCruise: +1,
  ButtonType.decelCruise: -1,
}

# Constants for Limit controllers.
LIMIT_ADAPT_ACC = -1.  # m/s^2 Ideal acceleration for the adapting (braking) phase when approaching speed limits.
LIMIT_MIN_ACC = -1.5  # m/s^2 Maximum deceleration allowed for limit controllers to provide.
LIMIT_MAX_ACC = 1.0   # m/s^2 Maximum acceleration allowed for limit controllers to provide while active.
LIMIT_MIN_SPEED = 8.33  # m/s, Minimum speed limit to provide as solution on limit controllers.
LIMIT_SPEED_OFFSET_TH = -1.  # m/s Maximum offset between speed limit and current speed for adapting state.
LIMIT_MAX_MAP_DATA_AGE = 10.  # s Maximum time to hold to map data, then consider it invalid inside limits controllers.

FCA_V_CRUISE_MIN = {
  True: 30,
  False: int(20 * CV.MPH_TO_KPH),
}
HONDA_V_CRUISE_MIN = {
  True: 40,
  False: int(25 * CV.MPH_TO_KPH),
}
HYUNDAI_V_CRUISE_MIN = {
  True: 30,
  False: int(20 * CV.MPH_TO_KPH),
}
MAZDA_V_CRUISE_MIN = {
  True: 30,
  False: int(20 * CV.MPH_TO_KPH),
}
VOLKSWAGEN_V_CRUISE_MIN = {
  True: 30,
  False: int(20 * CV.MPH_TO_KPH),
}

SpeedLimitControlState = custom.LongitudinalPlanSP.SpeedLimitControlState


class VCruiseHelper:
  def __init__(self, CP):
    self.CP = CP
    self.v_cruise_kph = V_CRUISE_UNSET
    self.v_cruise_cluster_kph = V_CRUISE_UNSET
    self.v_cruise_kph_last = 0
    self.button_timers = {ButtonType.decelCruise: 0, ButtonType.accelCruise: 0}
    self.button_change_states = {btn: {"standstill": False, "enabled": False} for btn in self.button_timers}

    self.is_metric_prev = None
    self.v_cruise_min = V_CRUISE_MIN
    self.slc_state = SpeedLimitControlState.inactive
    self.slc_state_prev = SpeedLimitControlState.inactive
    self.slc_speed_limit_offsetted = 0

  @property
  def v_cruise_initialized(self):
    return self.v_cruise_kph != V_CRUISE_UNSET

  def update_v_cruise(self, CS, enabled, is_metric, reverse_acc, long_plan_sp):
    self.v_cruise_kph_last = self.v_cruise_kph
    self.slc_state = long_plan_sp.speedLimitControlState

    if not self.CP.pcmCruiseSpeed:
      self._update_v_cruise_min(is_metric)

    if CS.cruiseState.available:
      if not self.CP.pcmCruise or not self.CP.pcmCruiseSpeed:
        # if stock cruise is completely disabled, then we can use our own set speed logic
        self._update_v_cruise_non_pcm(CS, enabled, is_metric, reverse_acc)
        self._update_v_cruise_slc(long_plan_sp)
        self.v_cruise_cluster_kph = self.v_cruise_kph
        self.update_button_timers(CS, enabled)
      else:
        self.v_cruise_kph = CS.cruiseState.speed * CV.MS_TO_KPH
        self.v_cruise_cluster_kph = CS.cruiseState.speedCluster * CV.MS_TO_KPH
    else:
      self.v_cruise_kph = V_CRUISE_UNSET
      self.v_cruise_cluster_kph = V_CRUISE_UNSET
  
  def _update_v_cruise_non_pcm(self, CS, enabled, is_metric, reverse_acc):
      """
      Updates cruise control speed based on button presses.
      Handles both short presses (small increments) and long presses (large increments with grid snapping).
      
      Args:
          CS: Car state containing button events and current vehicle status
          enabled: Whether cruise control is currently enabled
          is_metric: True for metric (kph), False for imperial (mph)
          reverse_acc: Reverses button behavior (long press = small increment, short = large)
      """
      
      # Early exit if cruise control is not enabled
      # TODO: this should be in state_control, but a decelCruise press
      # would have the effect of both enabling and changing speed is checked after the state transition
      if not enabled:
        return
      
      # Don't adjust speed during speed limit control state transition
      if self.slc_state == SpeedLimitControlState.active and self.slc_state_prev == SpeedLimitControlState.preActive:
        return
      
      # Initialize button detection variables
      long_press = False
      button_type = None
      
      # Process button events to detect what type of press occurred
      for b in CS.buttonEvents:
        if b.type.raw in self.button_timers and not b.pressed:
          # Button was released
          if self.button_timers[b.type.raw] > CRUISE_LONG_PRESS:
            # This was the end of a long press - don't process it again
            return
          # Short press detected - store the button type
          button_type = b.type.raw
          break
      else:
        # No button release found, check for ongoing long presses
        for k in self.button_timers.keys():
          # Check if button has been held long enough and we're at a long press interval
          if self.button_timers[k] and self.button_timers[k] % CRUISE_LONG_PRESS == 0:
            button_type = k
            long_press = True
            break
      
      # Exit if no button action to process
      if button_type is None:
        return
      
      # Don't process speed adjustments when car is not in a forward driving gear
      # This prevents errors when trying to adjust cruise speed while stopped
      # Note: This is AFTER button detection so it only blocks speed changes, not enable/disable
      if CS.gearShifter in [car.CarState.GearShifter.park, 
                            car.CarState.GearShifter.reverse,
                            car.CarState.GearShifter.neutral]:
        return
      
      # Also ignore speed adjustments if we're essentially stopped (under 0.5 m/s = 1.8 kph)
      # unless we have a valid cruise speed already set (for resume at traffic lights)
      if CS.vEgo < 0.5 and self.v_cruise_kph == V_CRUISE_UNSET:
        return
      
      # Determine which button is used for resume (varies by car model)
      resume_button = ButtonType.accelCruise
      if not self.CP.pcmCruiseSpeed:
        if self.CP.carName == "chrysler":
          resume_button = ButtonType.resumeCruise
      
      # Don't adjust speed when pressing resume to exit standstill
      # This prevents unintended speed changes when resuming from a stop
      cruise_standstill = self.button_change_states[button_type]["standstill"] or CS.cruiseState.standstill
      if button_type == resume_button and cruise_standstill:
        return
      
      # Don't adjust speed if cruise was enabled since the button was first pressed
      # Some car ports enable cruise on button rising edge, which could cause double action
      if not self.button_change_states[button_type]["enabled"]:
        return
      
      # ============ SPEED INCREMENT CALCULATION ============
      
      # Set up base increments and multipliers based on unit system
      if is_metric:
        # Metric mode: 1 kph for small increment
        v_cruise_delta = 1.0
        # Large increment: 10 kph (10x multiplier)
        v_cruise_delta_mltplr = 10
      else:
        # Imperial mode: 1 mph for small increment
        # Use exact conversion factor to avoid rounding issues (1 mph = 1.609344 kph)
        v_cruise_delta = CV.MPH_TO_KPH  # This is exactly 1.609344
        # Large increment: 5 mph (5x multiplier) - standard for most cars
        v_cruise_delta_mltplr = 5
      
      # Determine actual increment based on button press type and reverse_acc setting
      if reverse_acc:
        # Reversed mode: short press gives large increment, long press gives small increment
        # This is useful for users who want quick large adjustments with taps
        pressed_value = 1 if long_press else v_cruise_delta_mltplr
        # For grid snapping logic, we need to know if we're doing a "large" adjustment
        long_press_state = not long_press
      else:
        # Normal mode: short press gives small increment, long press gives large increment
        # This is the standard behavior most users expect
        pressed_value = v_cruise_delta_mltplr if long_press else 1
        long_press_state = long_press
      
      # Calculate final speed increment
      # For metric: 1 kph (short) or 10 kph (long)
      # For imperial: 1.609344 kph (short) or 8.04672 kph (long, which equals 5 mph)
      v_cruise_delta = v_cruise_delta * pressed_value
      
      # Get direction of adjustment (+1 for accel/resume, -1 for decel/set)
      dir_sign = CRUISE_INTERVAL_SIGN[button_type]
      
      # ============ GRID SNAPPING LOGIC (for large increments only) ============
      
      if long_press_state:
        # Large increment mode - need to handle grid alignment
        # This ensures speed stays on nice round numbers (e.g., 80, 85, 90 mph)
        
        # Calculate position on the grid
        # q represents how many "steps" we are from zero
        # For example, at 90 mph (144.84 kph) with 5 mph steps (8.04672 kph):
        # q = 144.84 / 8.04672 = 18.0 (exactly on grid)
        q = self.v_cruise_kph / v_cruise_delta
        
        # Tolerance for determining if we're "on grid"
        # 0.05 means we allow 5% deviation from exact grid alignment
        # This handles floating-point precision issues from repeated calculations
        eps = 0.05
        
        # Check if current speed is aligned to the grid
        # round(q) gives nearest grid position, abs difference tells us how far off we are
        if abs(q - round(q)) > eps:
          # We're NOT on a grid line - need to snap to the nearest grid line
          # in the direction of the button press
          
          if dir_sign > 0:
            # Accelerating: snap to next higher grid line
            # Example: 83 mph -> 85 mph when pressing accel
            self.v_cruise_kph = math.ceil(q) * v_cruise_delta
          else:
            # Decelerating: snap to next lower grid line
            # Example: 83 mph -> 80 mph when pressing decel
            self.v_cruise_kph = math.floor(q) * v_cruise_delta
        else:
          # We're already on a grid line (within tolerance)
          # Just advance by one full step in the requested direction
          # Example: 85 mph -> 90 mph (accel) or 85 mph -> 80 mph (decel)
          self.v_cruise_kph += dir_sign * v_cruise_delta
      else:
        # Small increment mode - no grid snapping needed
        # Just add/subtract the small increment
        # This allows fine-tuning between grid lines
        self.v_cruise_kph += dir_sign * v_cruise_delta
      
      # ============ SAFETY FEATURES AND FINAL PROCESSING ============
      
      # Special handling when driver is pressing gas pedal (overriding cruise)
      # If setting/reducing speed while overriding, don't go below current vehicle speed
      # This prevents setting cruise to a much lower speed than you're currently traveling
      if CS.gasPressed and button_type in (ButtonType.decelCruise, ButtonType.setCruise):
        self.v_cruise_kph = max(self.v_cruise_kph, CS.vEgo * CV.MS_TO_KPH)
      
      # Apply speed limits and round for display
      # - round to 0.1 kph for clean display values
      # - clip to minimum allowed speed (usually ~25 kph) and maximum (usually ~150 kph)
      self.v_cruise_kph = clip(round(self.v_cruise_kph, 1), self.v_cruise_min, V_CRUISE_MAX)


  def update_button_timers(self, CS, enabled):
    # increment timer for buttons still pressed
    for k in self.button_timers:
      if self.button_timers[k] > 0:
        self.button_timers[k] += 1

    for b in CS.buttonEvents:
      if b.type.raw in self.button_timers:
        # Start/end timer and store current state on change of button pressed
        self.button_timers[b.type.raw] = 1 if b.pressed else 0
        self.button_change_states[b.type.raw] = {"standstill": CS.cruiseState.standstill, "enabled": enabled}

  def initialize_v_cruise(self, CS, experimental_mode: bool, is_metric, dynamic_experimental_control: bool) -> None:
    # initializing is handled by the PCM
    if self.CP.pcmCruise and self.CP.pcmCruiseSpeed:
      return

    initial = V_CRUISE_INITIAL_EXPERIMENTAL_MODE if experimental_mode and not dynamic_experimental_control else V_CRUISE_INITIAL

    resume_buttons = (ButtonType.accelCruise, ButtonType.resumeCruise)

    if not self.CP.pcmCruiseSpeed:
      if self.CP.carName == "honda":
        initial = HONDA_V_CRUISE_MIN[is_metric]
      elif self.CP.carName == "hyundai":
        initial = HYUNDAI_V_CRUISE_MIN[is_metric]
      elif self.CP.carName == "chrysler":
        initial = FCA_V_CRUISE_MIN[is_metric]
        if not self.CP.pcmCruiseSpeed:
          resume_buttons = (ButtonType.resumeCruise,)
      elif self.CP.carName == "mazda":
        initial = MAZDA_V_CRUISE_MIN[is_metric]
      elif self.CP.carName == "volkswagen":
        initial = VOLKSWAGEN_V_CRUISE_MIN[is_metric]

    # 250kph or above probably means we never had a set speed
    if any(b.type in resume_buttons for b in CS.buttonEvents) and self.v_cruise_kph_last < 250:
      self.v_cruise_kph = self.v_cruise_kph_last
    else:
      self.v_cruise_kph = int(round(clip(CS.vEgo * CV.MS_TO_KPH, initial, V_CRUISE_MAX)))

    self.v_cruise_cluster_kph = self.v_cruise_kph

  def _update_v_cruise_slc(self, long_plan_sp):
    if self.slc_state == SpeedLimitControlState.active and self.slc_state_prev != SpeedLimitControlState.preActive:
      return

    self.slc_speed_limit_offsetted = (long_plan_sp.speedLimit + long_plan_sp.speedLimitOffset) * CV.MS_TO_KPH

    if self.slc_state == SpeedLimitControlState.active and self.slc_state_prev == SpeedLimitControlState.preActive:
      self.v_cruise_kph = clip(round(self.slc_speed_limit_offsetted, 1), self.v_cruise_min, V_CRUISE_MAX)

    self.slc_state_prev = self.slc_state

  def _update_v_cruise_min(self, is_metric):
    if is_metric != self.is_metric_prev:
      if self.CP.carName == "honda":
        self.v_cruise_min = HONDA_V_CRUISE_MIN[is_metric]
      elif self.CP.carName == "hyundai":
        self.v_cruise_min = HYUNDAI_V_CRUISE_MIN[is_metric]
      elif self.CP.carName == "chrysler":
        self.v_cruise_min = FCA_V_CRUISE_MIN[is_metric]
      elif self.CP.carName == "mazda":
        self.v_cruise_min = MAZDA_V_CRUISE_MIN[is_metric]
      elif self.CP.carName == "volkswagen":
        self.v_cruise_min = VOLKSWAGEN_V_CRUISE_MIN[is_metric]
    self.is_metric_prev = is_metric


def apply_deadzone(error, deadzone):
  if error > deadzone:
    error -= deadzone
  elif error < - deadzone:
    error += deadzone
  else:
    error = 0.
  return error


def apply_center_deadzone(error, deadzone):
  if (error > - deadzone) and (error < deadzone):
    error = 0.
  return error


def rate_limit(new_value, last_value, dw_step, up_step):
  return clip(new_value, last_value + dw_step, last_value + up_step)


def clip_curvature(v_ego, prev_curvature, new_curvature):
  v_ego = max(MIN_SPEED, v_ego)
  max_curvature_rate = MAX_LATERAL_JERK / (v_ego**2) # inexact calculation, check https://github.com/commaai/openpilot/pull/24755
  safe_desired_curvature = clip(new_curvature,
                                prev_curvature - max_curvature_rate * DT_CTRL,
                                prev_curvature + max_curvature_rate * DT_CTRL)

  return safe_desired_curvature


def get_lag_adjusted_curvature(CP, v_ego, psis, curvatures):
  if len(psis) != CONTROL_N:
    psis = [0.0]*CONTROL_N
    curvatures = [0.0]*CONTROL_N
  v_ego = max(MIN_SPEED, v_ego)

  # TODO this needs more thought, use .2s extra for now to estimate other delays
  delay = CP.steerActuatorDelay + .2

  # MPC can plan to turn the wheel and turn back before t_delay. This means
  # in high delay cases some corrections never even get commanded. So just use
  # psi to calculate a simple linearization of desired curvature
  current_curvature_desired = curvatures[0]
  psi = interp(delay, ModelConstants.T_IDXS[:CONTROL_N], psis)
  average_curvature_desired = psi / (v_ego * delay)
  desired_curvature = 2 * average_curvature_desired - current_curvature_desired

  # This is the "desired rate of the setpoint" not an actual desired rate
  max_curvature_rate = MAX_LATERAL_JERK / (v_ego**2) # inexact calculation, check https://github.com/commaai/openpilot/pull/24755
  safe_desired_curvature = clip(desired_curvature,
                                current_curvature_desired - max_curvature_rate * DT_MDL,
                                current_curvature_desired + max_curvature_rate * DT_MDL)

  return safe_desired_curvature


def get_friction(lateral_accel_error: float, lateral_accel_deadzone: float, friction_threshold: float,
                 torque_params: car.CarParams.LateralTorqueTuning, friction_compensation: bool) -> float:
  friction_interp = interp(
    apply_center_deadzone(lateral_accel_error, lateral_accel_deadzone),
    [-friction_threshold, friction_threshold],
    [-torque_params.friction, torque_params.friction]
  )
  friction = float(friction_interp) if friction_compensation else 0.0
  return friction


def get_speed_error(modelV2: log.ModelDataV2, v_ego: float) -> float:
  # ToDo: Try relative error, and absolute speed
  if len(modelV2.temporalPose.trans):
    vel_err = clip(modelV2.temporalPose.trans[0] - v_ego, -MAX_VEL_ERR, MAX_VEL_ERR)
    return float(vel_err)
  return 0.0


def get_road_edge(carstate, model_v2, toggle):
  # Lane detection by FrogAi
  one_blinker = carstate.leftBlinker != carstate.rightBlinker
  if not toggle:
    road_edge = False
  elif one_blinker:
    # Set the minimum lane threshold to 3.0 meters
    min_lane_threshold = 3.0
    # Set the blinker index based on which signal is on
    blinker_index = 0 if carstate.leftBlinker else 1
    desired_edge = model_v2.roadEdges[blinker_index]
    current_lane = model_v2.laneLines[blinker_index + 1]
    # Check if both the desired lane and the current lane have valid x and y values
    if all([desired_edge.x, desired_edge.y, current_lane.x, current_lane.y]) and len(desired_edge.x) == len(current_lane.x):
      # Interpolate the x and y values to the same length
      x = np.linspace(desired_edge.x[0], desired_edge.x[-1], num=len(desired_edge.x))
      lane_y = np.interp(x, current_lane.x, current_lane.y)
      desired_y = np.interp(x, desired_edge.x, desired_edge.y)
      # Calculate the width of the lane we're wanting to change into
      lane_width = np.abs(desired_y - lane_y)
      # Set road_edge to False if the lane width is not larger than the threshold
      road_edge = not (np.amax(lane_width) > min_lane_threshold)
    else:
      road_edge = True
  else:
    # Default to setting "road_edge" to False
    road_edge = False

  return road_edge
