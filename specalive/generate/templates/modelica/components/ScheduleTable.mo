// Purpose: the catalogue's schedule_table kind: a piecewise-constant signal, values[i] from
// times[i] until the next time, held after the last. Two 1-D arrays, so a schedule is two list
// parameters in the IR; the MSL CombiTimeTable with constant segments makes each step a time event.
block ScheduleTable "Piecewise-constant schedule"
  parameter Real times[:](each unit = "s") "Times the value changes, ascending";
  parameter Real values[size(times, 1)] "Value from each time until the next";
  SpecAlive.Interfaces.RealOutput y "Scheduled value" annotation(Placement(transformation(extent = {{80, -20}, {120, 20}}), iconTransformation(extent = {{80, -20}, {120, 20}})));
protected
  Modelica.Blocks.Sources.CombiTimeTable table(table = [times, values], smoothness = Modelica.Blocks.Types.Smoothness.ConstantSegments, extrapolation = Modelica.Blocks.Types.Extrapolation.HoldLastPoint) "Steps at each time";
equation
  y = table.y[1];
  annotation(Icon(coordinateSystem(extent = {{-100, -100}, {100, 100}}), graphics = {Rectangle(extent = {{-100, 100}, {100, -100}}, lineColor = {0, 0, 0}, fillColor = {255, 255, 255}, fillPattern = FillPattern.Solid), Text(extent = {{-100, 140}, {100, 105}}, textString = "%name", textColor = {0, 0, 255}), Text(extent = {{-90, 20}, {90, -20}}, textString = "schedule")}));
end ScheduleTable;
