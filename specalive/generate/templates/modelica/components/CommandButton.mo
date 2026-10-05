// Purpose: the catalogue's command_button kind: a momentary press is true for one pulse width from
// each press time, so a controller sees one rising edge per press. The pulses come from the MSL
// BooleanTable (switch times press, press + width, ...), whose time events omc schedules for every
// press; a `time >= pressTimes[i]` test inside a for loop was tracked for the last index only.
model CommandButton "Momentary pushbutton: true for one pulse width from each press time"
  parameter Real pressTimes[:](each unit = "s") = fill(0.0, 0) "Press times; none means never pressed";
  parameter Real width(unit = "s") = 1 "Pulse width of one press";
  SpecAlive.Interfaces.BooleanOutput y "True while pressed" annotation(Placement(transformation(extent = {{80, -20}, {120, 20}}), iconTransformation(extent = {{80, -20}, {120, 20}})));
protected
  Modelica.Blocks.Sources.BooleanTable table(table = {if mod(i, 2) == 1 then pressTimes[div(i + 1, 2)] else pressTimes[div(i, 2)] + width for i in 1:2 * size(pressTimes, 1)}, startValue = false) "Switches on at each press and off one width later";
equation
  y = table.y;
  annotation(Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 0}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-100, 140}, {100, 105}}, textString = "%name", textColor = {0, 0, 255}), Text(extent = {{-90, 20}, {90, -20}}, textString = "button")}));
end CommandButton;
