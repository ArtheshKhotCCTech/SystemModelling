// Purpose: the catalogue's schedule_table kind: a piecewise-constant signal, values[i] from
// times[i] until the next time, held after the last. Two 1-D arrays, so a schedule is two list
// parameters in the IR; the MSL CombiTimeTable with constant segments makes each step a time event.
block ScheduleTable "Piecewise-constant schedule"
  parameter Real times[:](each unit = "s") "Times the value changes, ascending";
  parameter Real values[size(times, 1)] "Value from each time until the next";
  SpecAlive.Interfaces.RealOutput y "Scheduled value";
protected
  Modelica.Blocks.Sources.CombiTimeTable table(table = [times, values], smoothness = Modelica.Blocks.Types.Smoothness.ConstantSegments, extrapolation = Modelica.Blocks.Types.Extrapolation.HoldLastPoint) "Steps at each time";
equation
  y = table.y[1];
end ScheduleTable;
