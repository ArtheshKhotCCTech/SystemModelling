function Modelica.Blocks.Tables.Internal.getNextTimeEvent "Return next time event value of 1-dim. table where first column is time"
  input Modelica.Blocks.Types.ExternalCombiTimeTable tableID "External table object";
  input Real timeIn "(Scaled) time value";
  output Real nextTimeEvent "(Scaled) next time event in table";

  external "C" nextTimeEvent = ModelicaStandardTables_CombiTimeTable_nextTimeEvent(tableID, timeIn);
end Modelica.Blocks.Tables.Internal.getNextTimeEvent;

function Modelica.Blocks.Tables.Internal.getTimeTableTmax "Return maximum abscissa value of 1-dim. table where first column is time"
  input Modelica.Blocks.Types.ExternalCombiTimeTable tableID "External table object";
  output Real timeMax "Maximum abscissa value in table";

  external "C" timeMax = ModelicaStandardTables_CombiTimeTable_maximumTime(tableID);
end Modelica.Blocks.Tables.Internal.getTimeTableTmax;

function Modelica.Blocks.Tables.Internal.getTimeTableTmin "Return minimum abscissa value of 1-dim. table where first column is time"
  input Modelica.Blocks.Types.ExternalCombiTimeTable tableID "External table object";
  output Real timeMin "Minimum abscissa value in table";

  external "C" timeMin = ModelicaStandardTables_CombiTimeTable_minimumTime(tableID);
end Modelica.Blocks.Tables.Internal.getTimeTableTmin;

function Modelica.Blocks.Tables.Internal.getTimeTableValueNoDer "Interpolate 1-dim. table where first column is time (but do not provide a derivative function)"
  input Modelica.Blocks.Types.ExternalCombiTimeTable tableID "External table object";
  input Integer icol "Column number";
  input Real timeIn "(Scaled) time value";
  input Real nextTimeEvent "(Scaled) next time event in table";
  input Real pre_nextTimeEvent "Pre-value of (scaled) next time event in table";
  output Real y "Interpolated value";

  external "C" y = ModelicaStandardTables_CombiTimeTable_getValue(tableID, icol, timeIn, nextTimeEvent, pre_nextTimeEvent);
end Modelica.Blocks.Tables.Internal.getTimeTableValueNoDer;

impure function Modelica.Blocks.Types.ExternalCombiTimeTable.constructor "Initialize 1-dim. table where first column is time"
  input String tableName "Table name";
  input String fileName "File name";
  input Real[:, :] table;
  input Real startTime;
  input Integer[:] columns;
  input enumeration(LinearSegments, ContinuousDerivative, ConstantSegments, MonotoneContinuousDerivative1, MonotoneContinuousDerivative2, ModifiedContinuousDerivative) smoothness;
  input enumeration(HoldLastPoint, LastTwoPoints, Periodic, NoExtrapolation) extrapolation;
  input Real shiftTime = 0.0;
  input enumeration(Always, AtDiscontinuities, NoTimeEvents) timeEvents = Modelica.Blocks.Types.TimeEvents.Always;
  input Boolean verboseRead = true "= true: Print info message; = false: No info message";
  input String delimiter = "," "Column delimiter character for CSV file";
  input Integer nHeaderLines = 0 "Number of header lines to ignore for CSV file";
  output Modelica.Blocks.Types.ExternalCombiTimeTable externalCombiTimeTable;

  external "C" externalCombiTimeTable = ModelicaStandardTables_CombiTimeTable_init3(fileName, tableName, table, size(table, 1), size(table, 2), startTime, columns, size(columns, 1), smoothness, extrapolation, shiftTime, timeEvents, verboseRead, delimiter, nHeaderLines);
end Modelica.Blocks.Types.ExternalCombiTimeTable.constructor;

impure function Modelica.Blocks.Types.ExternalCombiTimeTable.destructor "Terminate 1-dim. table where first column is time"
  input Modelica.Blocks.Types.ExternalCombiTimeTable externalCombiTimeTable;

  external "C" ModelicaStandardTables_CombiTimeTable_close(externalCombiTimeTable);
end Modelica.Blocks.Types.ExternalCombiTimeTable.destructor;

function two_tank_sequence.System.pb_shut.table.isValidTable "Check if table is valid"
  input Real[:] table "Vector of time instants";
  protected Integer n = size(table, 1) "Number of table points";
algorithm
  if n > 0 then
    for i in 2:n loop
      assert(table[i] > table[i - 1], "Time values of table not strict monotonically increasing: table[" + String(i - 1, 0, true) + "] = " + String(table[i - 1], 6, 0, true) + ", table[" + String(i, 0, true) + "] = " + String(table[i], 6, 0, true));
    end for;
  end if;
end two_tank_sequence.System.pb_shut.table.isValidTable;

function two_tank_sequence.System.pb_start.table.isValidTable "Check if table is valid"
  input Real[:] table "Vector of time instants";
  protected Integer n = size(table, 1) "Number of table points";
algorithm
  if n > 0 then
    for i in 2:n loop
      assert(table[i] > table[i - 1], "Time values of table not strict monotonically increasing: table[" + String(i - 1, 0, true) + "] = " + String(table[i - 1], 6, 0, true) + ", table[" + String(i, 0, true) + "] = " + String(table[i], 6, 0, true));
    end for;
  end if;
end two_tank_sequence.System.pb_start.table.isValidTable;

function two_tank_sequence.System.pb_stop.table.isValidTable "Check if table is valid"
  input Real[:] table "Vector of time instants";
  protected Integer n = size(table, 1) "Number of table points";
algorithm
  if n > 0 then
    for i in 2:n loop
      assert(table[i] > table[i - 1], "Time values of table not strict monotonically increasing: table[" + String(i - 1, 0, true) + "] = " + String(table[i - 1], 6, 0, true) + ", table[" + String(i, 0, true) + "] = " + String(table[i], 6, 0, true));
    end for;
  end if;
end two_tank_sequence.System.pb_stop.table.isValidTable;

class two_tank_sequence.System "two_tank_sequence: one instance per IR part and one connect per IR connection"
  parameter Real pb_shut_press_times[1](unit = "s") = 700.0 "pb_shut press_times, verification only [IR pb_shut_press_times]";
  parameter Real pb_start_press_times[1](unit = "s") = 20.0 "pb_start press_times, verification only [IR pb_start_press_times]";
  parameter Real pb_start_press_times[2](unit = "s") = 280.0 "pb_start press_times, verification only [IR pb_start_press_times]";
  parameter Real pb_stop_press_times[1](unit = "s") = 220.0 "pb_stop press_times, verification only [IR pb_stop_press_times]";
  parameter Real pb_stop_press_times[2](unit = "s") = 650.0 "pb_stop press_times, verification only [IR pb_stop_press_times]";
  parameter Real plc_101_scan_time(unit = "s") = 0.1 "plc_101 scan_time [IR plc_101_scan_time]";
  parameter Real plc_101_wait_after_drain(unit = "s") = 8.0 "plc_101 wait_after_drain [IR plc_101_wait_after_drain]";
  parameter Real plc_101_wait_after_fill(unit = "s") = 10.0 "plc_101 wait_after_fill [IR plc_101_wait_after_fill]";
  parameter Real plc_101_wait_after_transfer(unit = "s") = 12.0 "plc_101 wait_after_transfer [IR plc_101_wait_after_transfer]";
  parameter Real system_state_timing_tolerance(unit = "s") = 2.0 "system state_timing_tolerance, verification only [IR system_state_timing_tolerance]";
  parameter Real system_stop_time(unit = "s") = 900.0 "system stop_time, verification only [IR system_stop_time]";
  parameter Real tk_101_area(unit = "m2") = 1.2 "tk_101 area [IR tk_101_area]";
  parameter Real tk_101_height(unit = "m") = 1.0 "tk_101 height [IR tk_101_height]";
  parameter Real tk_101_high_level(unit = "m") = 0.8 "tk_101 high_level [IR tk_101_high_level]";
  parameter Real tk_101_initial_level(unit = "m") = 0.05 "tk_101 initial_level [IR tk_101_initial_level]";
  parameter Real tk_101_low_level(unit = "m") = 0.05 "tk_101 low_level [IR tk_101_low_level]";
  parameter Real tk_101_max_working_level(unit = "m") = 0.9 "tk_101 max_working_level [IR tk_101_max_working_level]";
  parameter Real tk_102_area(unit = "m2") = 1.4 "tk_102 area [IR tk_102_area]";
  parameter Real tk_102_height(unit = "m") = 1.0 "tk_102 height [IR tk_102_height]";
  parameter Real tk_102_initial_level(unit = "m") = 0.05 "tk_102 initial_level [IR tk_102_initial_level]";
  parameter Real tk_102_low_level(unit = "m") = 0.05 "tk_102 low_level [IR tk_102_low_level]";
  parameter Real tk_102_max_working_level(unit = "m") = 0.9 "tk_102 max_working_level [IR tk_102_max_working_level]";
  parameter Real xv_101_nominal_flow(unit = "m3/s") = 0.006 "xv_101 nominal_flow [IR xv_101_nominal_flow]";
  parameter Real xv_101_open_stroke_time(unit = "s") = 0.8 "xv_101 open_stroke_time [IR xv_101_open_stroke_time]";
  parameter Real xv_102_nominal_flow(unit = "m3/s") = 0.0045 "xv_102 nominal_flow [IR xv_102_nominal_flow]";
  parameter Real xv_102_open_stroke_time(unit = "s") = 0.8 "xv_102 open_stroke_time [IR xv_102_open_stroke_time]";
  parameter Real xv_103_nominal_flow(unit = "m3/s") = 0.005 "xv_103 nominal_flow [IR xv_103_nominal_flow]";
  parameter Real xv_103_open_stroke_time(unit = "s") = 0.8 "xv_103 open_stroke_time [IR xv_103_open_stroke_time]";
  Real drn_101.inlet(unit = "m3/s") "Flow delivered by the upstream component";
  Real lt_101.u "Connector of Real input signal";
  Real lt_101.y "Connector of Real output signal";
  Real lt_102.u "Connector of Real input signal";
  Real lt_102.y "Connector of Real output signal";
  parameter Real pb_shut.pressTimes[1](unit = "s") = pb_shut_press_times[1] "Press times; none means never pressed";
  parameter Real pb_shut.width(unit = "s") = 1.0 "Pulse width of one press";
  Boolean pb_shut.y "True while pressed";
  protected parameter Real pb_shut.table.table[1](quantity = "Time", unit = "s") = pb_shut.pressTimes[1] "Vector of time points. At every time point, the output y gets its opposite value (e.g., table={0,1})";
  protected parameter Real pb_shut.table.table[2](quantity = "Time", unit = "s") = pb_shut.pressTimes[1] + pb_shut.width "Vector of time points. At every time point, the output y gets its opposite value (e.g., table={0,1})";
  protected parameter Boolean pb_shut.table.startValue = false "Start value of y. At time = table[1], y changes to 'not startValue'";
  protected final parameter enumeration(HoldLastPoint, LastTwoPoints, Periodic, NoExtrapolation) pb_shut.table.extrapolation = Modelica.Blocks.Types.Extrapolation.HoldLastPoint "Extrapolation of data outside the definition range";
  protected parameter Real pb_shut.table.startTime(quantity = "Time", unit = "s") = -1e60 "Output = false for time < startTime";
  protected parameter Real pb_shut.table.shiftTime(quantity = "Time", unit = "s") = 0.0 "Shift time of table";
  protected Boolean pb_shut.table.y "Connector of Boolean output signal";
  protected final parameter Integer pb_shut.table.combiTimeTable.nout(min = 1) = 1 "Number of outputs";
  protected Real pb_shut.table.combiTimeTable.y[1] "Connector of Real output signals";
  protected final parameter Boolean pb_shut.table.combiTimeTable.tableOnFile = false "= true, if table is defined on file or in function usertab";
  protected final parameter Real pb_shut.table.combiTimeTable.table[1,1] = if pb_shut.table.startValue then pb_shut.table.table[1] else pb_shut.table.table[1] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_shut.table.combiTimeTable.table[1,2] = if pb_shut.table.startValue then 1.0 else 0.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_shut.table.combiTimeTable.table[2,1] = if pb_shut.table.startValue then pb_shut.table.table[1] else pb_shut.table.table[1] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_shut.table.combiTimeTable.table[2,2] = if pb_shut.table.startValue then 0.0 else 1.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_shut.table.combiTimeTable.table[3,1] = if pb_shut.table.startValue then pb_shut.table.table[2] else pb_shut.table.table[2] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_shut.table.combiTimeTable.table[3,2] = if pb_shut.table.startValue then 1.0 else 0.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected parameter String pb_shut.table.combiTimeTable.tableName = "NoName" "Table name on file or in function usertab (see docu)";
  protected parameter String pb_shut.table.combiTimeTable.fileName = "NoName" "File where matrix is stored";
  protected parameter String pb_shut.table.combiTimeTable.delimiter = "," "Column delimiter character for CSV file";
  protected parameter Integer pb_shut.table.combiTimeTable.nHeaderLines = 0 "Number of header lines to ignore for CSV file";
  protected parameter Boolean pb_shut.table.combiTimeTable.verboseRead = true "= true, if info message that file is loading is to be printed";
  protected final parameter Integer pb_shut.table.combiTimeTable.columns[1] = 2 "Columns of table to be interpolated";
  protected final parameter enumeration(LinearSegments, ContinuousDerivative, ConstantSegments, MonotoneContinuousDerivative1, MonotoneContinuousDerivative2, ModifiedContinuousDerivative) pb_shut.table.combiTimeTable.smoothness = Modelica.Blocks.Types.Smoothness.ConstantSegments "Smoothness of table interpolation";
  protected final parameter enumeration(HoldLastPoint, LastTwoPoints, Periodic, NoExtrapolation) pb_shut.table.combiTimeTable.extrapolation = Modelica.Blocks.Types.Extrapolation.HoldLastPoint "Extrapolation of data outside the definition range";
  protected final parameter Real pb_shut.table.combiTimeTable.timeScale(quantity = "Time", unit = "s", min = 2.220446049250313e-16) = 1.0 "Time scale of first table column";
  protected parameter Real pb_shut.table.combiTimeTable.offset[1] = 0.0 "Offsets of output signals";
  protected final parameter Real pb_shut.table.combiTimeTable.startTime(quantity = "Time", unit = "s") = pb_shut.table.startTime "Output = offset for time < startTime";
  protected final parameter Real pb_shut.table.combiTimeTable.shiftTime(quantity = "Time", unit = "s") = pb_shut.table.shiftTime "Shift time of first table column";
  protected parameter enumeration(Always, AtDiscontinuities, NoTimeEvents) pb_shut.table.combiTimeTable.timeEvents = Modelica.Blocks.Types.TimeEvents.Always "Time event handling of table interpolation";
  protected final parameter Boolean pb_shut.table.combiTimeTable.verboseExtrapolation = false "= true, if warning messages are to be printed if time is outside the table definition range";
  protected final parameter Real pb_shut.table.combiTimeTable.t_min(quantity = "Time", unit = "s") = pb_shut.table.combiTimeTable.t_minScaled "Minimum abscissa value defined in table";
  protected final parameter Real pb_shut.table.combiTimeTable.t_max(quantity = "Time", unit = "s") = pb_shut.table.combiTimeTable.t_maxScaled "Maximum abscissa value defined in table";
  protected final parameter Real pb_shut.table.combiTimeTable.t_minScaled = Modelica.Blocks.Tables.Internal.getTimeTableTmin(pb_shut.table.combiTimeTable.tableID) "Minimum (scaled) abscissa value defined in table";
  protected final parameter Real pb_shut.table.combiTimeTable.t_maxScaled = Modelica.Blocks.Tables.Internal.getTimeTableTmax(pb_shut.table.combiTimeTable.tableID) "Maximum (scaled) abscissa value defined in table";
  protected final parameter Real pb_shut.table.combiTimeTable.p_offset[1] = pb_shut.table.combiTimeTable.offset[1] "Offsets of output signals";
  protected parameter Modelica.Blocks.Types.ExternalCombiTimeTable pb_shut.table.combiTimeTable.tableID = Modelica.Blocks.Types.ExternalCombiTimeTable.constructor("NoName", "NoName", pb_shut.table.combiTimeTable.table, pb_shut.table.combiTimeTable.startTime, pb_shut.table.combiTimeTable.columns, Modelica.Blocks.Types.Smoothness.ConstantSegments, Modelica.Blocks.Types.Extrapolation.HoldLastPoint, pb_shut.table.combiTimeTable.shiftTime, Modelica.Blocks.Types.TimeEvents.Always, false, pb_shut.table.combiTimeTable.delimiter, pb_shut.table.combiTimeTable.nHeaderLines) "External table object";
  protected discrete Real pb_shut.table.combiTimeTable.nextTimeEvent(quantity = "Time", unit = "s", start = 0.0, fixed = true) "Next time event instant";
  protected discrete Real pb_shut.table.combiTimeTable.nextTimeEventScaled(start = 0.0, fixed = true) "Next scaled time event instant";
  protected Real pb_shut.table.combiTimeTable.timeScaled "Scaled time";
  protected final parameter Boolean pb_shut.table.combiTimeTable.isCsvExt = false;
  protected Real pb_shut.table.realToBoolean.u "Connector of Real input signal";
  protected Boolean pb_shut.table.realToBoolean.y "Connector of Boolean output signal";
  protected parameter Real pb_shut.table.realToBoolean.threshold = 0.5 "Output signal y is true, if input u >= threshold";
  protected final parameter Integer pb_shut.table.n = 2 "Number of table points";
  parameter Real pb_start.pressTimes[1](unit = "s") = pb_start_press_times[1] "Press times; none means never pressed";
  parameter Real pb_start.pressTimes[2](unit = "s") = pb_start_press_times[2] "Press times; none means never pressed";
  parameter Real pb_start.width(unit = "s") = 1.0 "Pulse width of one press";
  Boolean pb_start.y "True while pressed";
  protected parameter Real pb_start.table.table[1](quantity = "Time", unit = "s") = pb_start.pressTimes[1] "Vector of time points. At every time point, the output y gets its opposite value (e.g., table={0,1})";
  protected parameter Real pb_start.table.table[2](quantity = "Time", unit = "s") = pb_start.pressTimes[1] + pb_start.width "Vector of time points. At every time point, the output y gets its opposite value (e.g., table={0,1})";
  protected parameter Real pb_start.table.table[3](quantity = "Time", unit = "s") = pb_start.pressTimes[2] "Vector of time points. At every time point, the output y gets its opposite value (e.g., table={0,1})";
  protected parameter Real pb_start.table.table[4](quantity = "Time", unit = "s") = pb_start.pressTimes[2] + pb_start.width "Vector of time points. At every time point, the output y gets its opposite value (e.g., table={0,1})";
  protected parameter Boolean pb_start.table.startValue = false "Start value of y. At time = table[1], y changes to 'not startValue'";
  protected final parameter enumeration(HoldLastPoint, LastTwoPoints, Periodic, NoExtrapolation) pb_start.table.extrapolation = Modelica.Blocks.Types.Extrapolation.HoldLastPoint "Extrapolation of data outside the definition range";
  protected parameter Real pb_start.table.startTime(quantity = "Time", unit = "s") = -1e60 "Output = false for time < startTime";
  protected parameter Real pb_start.table.shiftTime(quantity = "Time", unit = "s") = 0.0 "Shift time of table";
  protected Boolean pb_start.table.y "Connector of Boolean output signal";
  protected final parameter Integer pb_start.table.combiTimeTable.nout(min = 1) = 1 "Number of outputs";
  protected Real pb_start.table.combiTimeTable.y[1] "Connector of Real output signals";
  protected final parameter Boolean pb_start.table.combiTimeTable.tableOnFile = false "= true, if table is defined on file or in function usertab";
  protected final parameter Real pb_start.table.combiTimeTable.table[1,1] = if pb_start.table.startValue then pb_start.table.table[1] else pb_start.table.table[1] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_start.table.combiTimeTable.table[1,2] = if pb_start.table.startValue then 1.0 else 0.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_start.table.combiTimeTable.table[2,1] = if pb_start.table.startValue then pb_start.table.table[1] else pb_start.table.table[1] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_start.table.combiTimeTable.table[2,2] = if pb_start.table.startValue then 0.0 else 1.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_start.table.combiTimeTable.table[3,1] = if pb_start.table.startValue then pb_start.table.table[2] else pb_start.table.table[2] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_start.table.combiTimeTable.table[3,2] = if pb_start.table.startValue then 1.0 else 0.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_start.table.combiTimeTable.table[4,1] = if pb_start.table.startValue then pb_start.table.table[3] else pb_start.table.table[3] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_start.table.combiTimeTable.table[4,2] = if pb_start.table.startValue then 0.0 else 1.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_start.table.combiTimeTable.table[5,1] = if pb_start.table.startValue then pb_start.table.table[4] else pb_start.table.table[4] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_start.table.combiTimeTable.table[5,2] = if pb_start.table.startValue then 1.0 else 0.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected parameter String pb_start.table.combiTimeTable.tableName = "NoName" "Table name on file or in function usertab (see docu)";
  protected parameter String pb_start.table.combiTimeTable.fileName = "NoName" "File where matrix is stored";
  protected parameter String pb_start.table.combiTimeTable.delimiter = "," "Column delimiter character for CSV file";
  protected parameter Integer pb_start.table.combiTimeTable.nHeaderLines = 0 "Number of header lines to ignore for CSV file";
  protected parameter Boolean pb_start.table.combiTimeTable.verboseRead = true "= true, if info message that file is loading is to be printed";
  protected final parameter Integer pb_start.table.combiTimeTable.columns[1] = 2 "Columns of table to be interpolated";
  protected final parameter enumeration(LinearSegments, ContinuousDerivative, ConstantSegments, MonotoneContinuousDerivative1, MonotoneContinuousDerivative2, ModifiedContinuousDerivative) pb_start.table.combiTimeTable.smoothness = Modelica.Blocks.Types.Smoothness.ConstantSegments "Smoothness of table interpolation";
  protected final parameter enumeration(HoldLastPoint, LastTwoPoints, Periodic, NoExtrapolation) pb_start.table.combiTimeTable.extrapolation = Modelica.Blocks.Types.Extrapolation.HoldLastPoint "Extrapolation of data outside the definition range";
  protected final parameter Real pb_start.table.combiTimeTable.timeScale(quantity = "Time", unit = "s", min = 2.220446049250313e-16) = 1.0 "Time scale of first table column";
  protected parameter Real pb_start.table.combiTimeTable.offset[1] = 0.0 "Offsets of output signals";
  protected final parameter Real pb_start.table.combiTimeTable.startTime(quantity = "Time", unit = "s") = pb_start.table.startTime "Output = offset for time < startTime";
  protected final parameter Real pb_start.table.combiTimeTable.shiftTime(quantity = "Time", unit = "s") = pb_start.table.shiftTime "Shift time of first table column";
  protected parameter enumeration(Always, AtDiscontinuities, NoTimeEvents) pb_start.table.combiTimeTable.timeEvents = Modelica.Blocks.Types.TimeEvents.Always "Time event handling of table interpolation";
  protected final parameter Boolean pb_start.table.combiTimeTable.verboseExtrapolation = false "= true, if warning messages are to be printed if time is outside the table definition range";
  protected final parameter Real pb_start.table.combiTimeTable.t_min(quantity = "Time", unit = "s") = pb_start.table.combiTimeTable.t_minScaled "Minimum abscissa value defined in table";
  protected final parameter Real pb_start.table.combiTimeTable.t_max(quantity = "Time", unit = "s") = pb_start.table.combiTimeTable.t_maxScaled "Maximum abscissa value defined in table";
  protected final parameter Real pb_start.table.combiTimeTable.t_minScaled = Modelica.Blocks.Tables.Internal.getTimeTableTmin(pb_start.table.combiTimeTable.tableID) "Minimum (scaled) abscissa value defined in table";
  protected final parameter Real pb_start.table.combiTimeTable.t_maxScaled = Modelica.Blocks.Tables.Internal.getTimeTableTmax(pb_start.table.combiTimeTable.tableID) "Maximum (scaled) abscissa value defined in table";
  protected final parameter Real pb_start.table.combiTimeTable.p_offset[1] = pb_start.table.combiTimeTable.offset[1] "Offsets of output signals";
  protected parameter Modelica.Blocks.Types.ExternalCombiTimeTable pb_start.table.combiTimeTable.tableID = Modelica.Blocks.Types.ExternalCombiTimeTable.constructor("NoName", "NoName", pb_start.table.combiTimeTable.table, pb_start.table.combiTimeTable.startTime, pb_start.table.combiTimeTable.columns, Modelica.Blocks.Types.Smoothness.ConstantSegments, Modelica.Blocks.Types.Extrapolation.HoldLastPoint, pb_start.table.combiTimeTable.shiftTime, Modelica.Blocks.Types.TimeEvents.Always, false, pb_start.table.combiTimeTable.delimiter, pb_start.table.combiTimeTable.nHeaderLines) "External table object";
  protected discrete Real pb_start.table.combiTimeTable.nextTimeEvent(quantity = "Time", unit = "s", start = 0.0, fixed = true) "Next time event instant";
  protected discrete Real pb_start.table.combiTimeTable.nextTimeEventScaled(start = 0.0, fixed = true) "Next scaled time event instant";
  protected Real pb_start.table.combiTimeTable.timeScaled "Scaled time";
  protected final parameter Boolean pb_start.table.combiTimeTable.isCsvExt = false;
  protected Real pb_start.table.realToBoolean.u "Connector of Real input signal";
  protected Boolean pb_start.table.realToBoolean.y "Connector of Boolean output signal";
  protected parameter Real pb_start.table.realToBoolean.threshold = 0.5 "Output signal y is true, if input u >= threshold";
  protected final parameter Integer pb_start.table.n = 4 "Number of table points";
  parameter Real pb_stop.pressTimes[1](unit = "s") = pb_stop_press_times[1] "Press times; none means never pressed";
  parameter Real pb_stop.pressTimes[2](unit = "s") = pb_stop_press_times[2] "Press times; none means never pressed";
  parameter Real pb_stop.width(unit = "s") = 1.0 "Pulse width of one press";
  Boolean pb_stop.y "True while pressed";
  protected parameter Real pb_stop.table.table[1](quantity = "Time", unit = "s") = pb_stop.pressTimes[1] "Vector of time points. At every time point, the output y gets its opposite value (e.g., table={0,1})";
  protected parameter Real pb_stop.table.table[2](quantity = "Time", unit = "s") = pb_stop.pressTimes[1] + pb_stop.width "Vector of time points. At every time point, the output y gets its opposite value (e.g., table={0,1})";
  protected parameter Real pb_stop.table.table[3](quantity = "Time", unit = "s") = pb_stop.pressTimes[2] "Vector of time points. At every time point, the output y gets its opposite value (e.g., table={0,1})";
  protected parameter Real pb_stop.table.table[4](quantity = "Time", unit = "s") = pb_stop.pressTimes[2] + pb_stop.width "Vector of time points. At every time point, the output y gets its opposite value (e.g., table={0,1})";
  protected parameter Boolean pb_stop.table.startValue = false "Start value of y. At time = table[1], y changes to 'not startValue'";
  protected final parameter enumeration(HoldLastPoint, LastTwoPoints, Periodic, NoExtrapolation) pb_stop.table.extrapolation = Modelica.Blocks.Types.Extrapolation.HoldLastPoint "Extrapolation of data outside the definition range";
  protected parameter Real pb_stop.table.startTime(quantity = "Time", unit = "s") = -1e60 "Output = false for time < startTime";
  protected parameter Real pb_stop.table.shiftTime(quantity = "Time", unit = "s") = 0.0 "Shift time of table";
  protected Boolean pb_stop.table.y "Connector of Boolean output signal";
  protected final parameter Integer pb_stop.table.combiTimeTable.nout(min = 1) = 1 "Number of outputs";
  protected Real pb_stop.table.combiTimeTable.y[1] "Connector of Real output signals";
  protected final parameter Boolean pb_stop.table.combiTimeTable.tableOnFile = false "= true, if table is defined on file or in function usertab";
  protected final parameter Real pb_stop.table.combiTimeTable.table[1,1] = if pb_stop.table.startValue then pb_stop.table.table[1] else pb_stop.table.table[1] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_stop.table.combiTimeTable.table[1,2] = if pb_stop.table.startValue then 1.0 else 0.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_stop.table.combiTimeTable.table[2,1] = if pb_stop.table.startValue then pb_stop.table.table[1] else pb_stop.table.table[1] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_stop.table.combiTimeTable.table[2,2] = if pb_stop.table.startValue then 0.0 else 1.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_stop.table.combiTimeTable.table[3,1] = if pb_stop.table.startValue then pb_stop.table.table[2] else pb_stop.table.table[2] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_stop.table.combiTimeTable.table[3,2] = if pb_stop.table.startValue then 1.0 else 0.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_stop.table.combiTimeTable.table[4,1] = if pb_stop.table.startValue then pb_stop.table.table[3] else pb_stop.table.table[3] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_stop.table.combiTimeTable.table[4,2] = if pb_stop.table.startValue then 0.0 else 1.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_stop.table.combiTimeTable.table[5,1] = if pb_stop.table.startValue then pb_stop.table.table[4] else pb_stop.table.table[4] "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected final parameter Real pb_stop.table.combiTimeTable.table[5,2] = if pb_stop.table.startValue then 1.0 else 0.0 "Table matrix (time = first column; e.g., table=[0, 0; 1, 1; 2, 4])";
  protected parameter String pb_stop.table.combiTimeTable.tableName = "NoName" "Table name on file or in function usertab (see docu)";
  protected parameter String pb_stop.table.combiTimeTable.fileName = "NoName" "File where matrix is stored";
  protected parameter String pb_stop.table.combiTimeTable.delimiter = "," "Column delimiter character for CSV file";
  protected parameter Integer pb_stop.table.combiTimeTable.nHeaderLines = 0 "Number of header lines to ignore for CSV file";
  protected parameter Boolean pb_stop.table.combiTimeTable.verboseRead = true "= true, if info message that file is loading is to be printed";
  protected final parameter Integer pb_stop.table.combiTimeTable.columns[1] = 2 "Columns of table to be interpolated";
  protected final parameter enumeration(LinearSegments, ContinuousDerivative, ConstantSegments, MonotoneContinuousDerivative1, MonotoneContinuousDerivative2, ModifiedContinuousDerivative) pb_stop.table.combiTimeTable.smoothness = Modelica.Blocks.Types.Smoothness.ConstantSegments "Smoothness of table interpolation";
  protected final parameter enumeration(HoldLastPoint, LastTwoPoints, Periodic, NoExtrapolation) pb_stop.table.combiTimeTable.extrapolation = Modelica.Blocks.Types.Extrapolation.HoldLastPoint "Extrapolation of data outside the definition range";
  protected final parameter Real pb_stop.table.combiTimeTable.timeScale(quantity = "Time", unit = "s", min = 2.220446049250313e-16) = 1.0 "Time scale of first table column";
  protected parameter Real pb_stop.table.combiTimeTable.offset[1] = 0.0 "Offsets of output signals";
  protected final parameter Real pb_stop.table.combiTimeTable.startTime(quantity = "Time", unit = "s") = pb_stop.table.startTime "Output = offset for time < startTime";
  protected final parameter Real pb_stop.table.combiTimeTable.shiftTime(quantity = "Time", unit = "s") = pb_stop.table.shiftTime "Shift time of first table column";
  protected parameter enumeration(Always, AtDiscontinuities, NoTimeEvents) pb_stop.table.combiTimeTable.timeEvents = Modelica.Blocks.Types.TimeEvents.Always "Time event handling of table interpolation";
  protected final parameter Boolean pb_stop.table.combiTimeTable.verboseExtrapolation = false "= true, if warning messages are to be printed if time is outside the table definition range";
  protected final parameter Real pb_stop.table.combiTimeTable.t_min(quantity = "Time", unit = "s") = pb_stop.table.combiTimeTable.t_minScaled "Minimum abscissa value defined in table";
  protected final parameter Real pb_stop.table.combiTimeTable.t_max(quantity = "Time", unit = "s") = pb_stop.table.combiTimeTable.t_maxScaled "Maximum abscissa value defined in table";
  protected final parameter Real pb_stop.table.combiTimeTable.t_minScaled = Modelica.Blocks.Tables.Internal.getTimeTableTmin(pb_stop.table.combiTimeTable.tableID) "Minimum (scaled) abscissa value defined in table";
  protected final parameter Real pb_stop.table.combiTimeTable.t_maxScaled = Modelica.Blocks.Tables.Internal.getTimeTableTmax(pb_stop.table.combiTimeTable.tableID) "Maximum (scaled) abscissa value defined in table";
  protected final parameter Real pb_stop.table.combiTimeTable.p_offset[1] = pb_stop.table.combiTimeTable.offset[1] "Offsets of output signals";
  protected parameter Modelica.Blocks.Types.ExternalCombiTimeTable pb_stop.table.combiTimeTable.tableID = Modelica.Blocks.Types.ExternalCombiTimeTable.constructor("NoName", "NoName", pb_stop.table.combiTimeTable.table, pb_stop.table.combiTimeTable.startTime, pb_stop.table.combiTimeTable.columns, Modelica.Blocks.Types.Smoothness.ConstantSegments, Modelica.Blocks.Types.Extrapolation.HoldLastPoint, pb_stop.table.combiTimeTable.shiftTime, Modelica.Blocks.Types.TimeEvents.Always, false, pb_stop.table.combiTimeTable.delimiter, pb_stop.table.combiTimeTable.nHeaderLines) "External table object";
  protected discrete Real pb_stop.table.combiTimeTable.nextTimeEvent(quantity = "Time", unit = "s", start = 0.0, fixed = true) "Next time event instant";
  protected discrete Real pb_stop.table.combiTimeTable.nextTimeEventScaled(start = 0.0, fixed = true) "Next scaled time event instant";
  protected Real pb_stop.table.combiTimeTable.timeScaled "Scaled time";
  protected final parameter Boolean pb_stop.table.combiTimeTable.isCsvExt = false;
  protected Real pb_stop.table.realToBoolean.u "Connector of Real input signal";
  protected Boolean pb_stop.table.realToBoolean.y "Connector of Boolean output signal";
  protected parameter Real pb_stop.table.realToBoolean.threshold = 0.5 "Output signal y is true, if input u >= threshold";
  protected final parameter Integer pb_stop.table.n = 4 "Number of table points";
  Real plc_101.level1(unit = "m") "[IR plc_101_level1]";
  Real plc_101.level2(unit = "m") "[IR plc_101_level2]";
  Boolean plc_101.start "[IR plc_101_start]";
  Boolean plc_101.stop "[IR plc_101_stop]";
  Boolean plc_101.shut "[IR plc_101_shut]";
  Boolean plc_101.valve1 "[IR plc_101_valve1]";
  Boolean plc_101.valve2 "[IR plc_101_valve2]";
  Boolean plc_101.valve3 "[IR plc_101_valve3]";
  parameter Real plc_101.plc_101_wait_after_drain(unit = "s") = plc_101_wait_after_drain "[IR plc_101_wait_after_drain]";
  parameter Real plc_101.plc_101_wait_after_fill(unit = "s") = plc_101_wait_after_fill "[IR plc_101_wait_after_fill]";
  parameter Real plc_101.plc_101_wait_after_transfer(unit = "s") = plc_101_wait_after_transfer "[IR plc_101_wait_after_transfer]";
  parameter Real plc_101.tk_101_high_level(unit = "m") = tk_101_high_level "[IR tk_101_high_level]";
  parameter Real plc_101.tk_101_low_level(unit = "m") = tk_101_low_level "[IR tk_101_low_level]";
  parameter Real plc_101.tk_102_low_level(unit = "m") = tk_102_low_level "[IR tk_102_low_level]";
  enumeration(idle, fill_t1, wait_after_fill, transfer_t1_t2, wait_after_transfer, drain_t2, wait_after_drain, paused, shutdown) plc_101.state(start = plc_101.State.idle, fixed = true) "Active state";
  enumeration(idle, fill_t1, wait_after_fill, transfer_t1_t2, wait_after_transfer, drain_t2, wait_after_drain, paused, shutdown) plc_101.history_state(start = plc_101.State.idle, fixed = true) "State a history return goes back to";
  discrete Real plc_101.wait_after_fill_timer_deadline(start = 1e60, fixed = true) "Time the timer expires [IR wait_after_fill_timer]";
  discrete Real plc_101.wait_after_fill_timer_remaining(start = 0.0, fixed = true) "Time left when frozen [IR wait_after_fill_timer]";
  discrete Real plc_101.wait_after_transfer_timer_deadline(start = 1e60, fixed = true) "Time the timer expires [IR wait_after_transfer_timer]";
  discrete Real plc_101.wait_after_transfer_timer_remaining(start = 0.0, fixed = true) "Time left when frozen [IR wait_after_transfer_timer]";
  discrete Real plc_101.wait_after_drain_timer_deadline(start = 1e60, fixed = true) "Time the timer expires [IR wait_after_drain_timer]";
  discrete Real plc_101.wait_after_drain_timer_remaining(start = 0.0, fixed = true) "Time left when frozen [IR wait_after_drain_timer]";
  Real src_101.outlet(unit = "m3/s") "Flow drawn by the downstream component";
  parameter Real tk_101.A(unit = "m2") = tk_101_area "Cross-section area";
  parameter Real tk_101.h_start(unit = "m") = tk_101_initial_level "Initial level";
  Real tk_101.inlet(unit = "m3/s") "Inflow, set by the upstream component";
  Real tk_101.outlet(unit = "m3/s") "Outflow, set by the downstream component";
  Real tk_101.level(unit = "m") "Liquid level";
  Real tk_101.h(unit = "m", start = tk_101.h_start, fixed = true) "Liquid level";
  parameter Real tk_102.A(unit = "m2") = tk_102_area "Cross-section area";
  parameter Real tk_102.h_start(unit = "m") = tk_102_initial_level "Initial level";
  Real tk_102.inlet(unit = "m3/s") "Inflow, set by the upstream component";
  Real tk_102.outlet(unit = "m3/s") "Outflow, set by the downstream component";
  Real tk_102.level(unit = "m") "Liquid level";
  Real tk_102.h(unit = "m", start = tk_102.h_start, fixed = true) "Liquid level";
  parameter Real xv_101.q_nominal(unit = "m3/s") = xv_101_nominal_flow "Flow when open";
  Real xv_101.inlet(unit = "m3/s") "Flow drawn from upstream";
  Real xv_101.outlet(unit = "m3/s") "Flow delivered downstream";
  Boolean xv_101.open "True commands the valve open";
  parameter Real xv_102.q_nominal(unit = "m3/s") = xv_102_nominal_flow "Flow when open";
  Real xv_102.inlet(unit = "m3/s") "Flow drawn from upstream";
  Real xv_102.outlet(unit = "m3/s") "Flow delivered downstream";
  Boolean xv_102.open "True commands the valve open";
  parameter Real xv_103.q_nominal(unit = "m3/s") = xv_103_nominal_flow "Flow when open";
  Real xv_103.inlet(unit = "m3/s") "Flow drawn from upstream";
  Real xv_103.outlet(unit = "m3/s") "Flow delivered downstream";
  Boolean xv_103.open "True commands the valve open";
initial algorithm
  two_tank_sequence.System.pb_shut.table.isValidTable(pb_shut.table.table);
initial algorithm
  two_tank_sequence.System.pb_start.table.isValidTable(pb_start.table.table);
initial algorithm
  two_tank_sequence.System.pb_stop.table.isValidTable(pb_stop.table.table);
equation
  pb_shut.table.combiTimeTable.y[1] = pb_shut.table.realToBoolean.u;
  pb_shut.table.realToBoolean.y = pb_shut.table.y;
  pb_start.table.combiTimeTable.y[1] = pb_start.table.realToBoolean.u;
  pb_start.table.realToBoolean.y = pb_start.table.y;
  pb_stop.table.combiTimeTable.y[1] = pb_stop.table.realToBoolean.u;
  pb_stop.table.realToBoolean.y = pb_stop.table.y;
  lt_101.y = plc_101.level1 "level measurement [IR if_ctl_01]";
  lt_102.y = plc_101.level2 "level measurement [IR if_ctl_02]";
  pb_start.y = plc_101.start "command [IR if_ctl_03]";
  pb_stop.y = plc_101.stop "command [IR if_ctl_04]";
  pb_shut.y = plc_101.shut "command [IR if_ctl_05]";
  plc_101.valve1 = xv_101.open "open command [IR if_ctl_06]";
  plc_101.valve2 = xv_102.open "open command [IR if_ctl_07]";
  plc_101.valve3 = xv_103.open "open command [IR if_ctl_08]";
  src_101.outlet = xv_101.inlet "liquid [IR if_hyd_01]";
  xv_101.outlet = tk_101.inlet "liquid [IR if_hyd_02]";
  tk_101.outlet = xv_102.inlet "liquid [IR if_hyd_03]";
  xv_102.outlet = tk_102.inlet "liquid [IR if_hyd_04]";
  tk_102.outlet = xv_103.inlet "liquid [IR if_hyd_05]";
  xv_103.outlet = drn_101.inlet "liquid [IR if_hyd_06]";
  tk_101.level = lt_101.u "level [IR tk_101_lt_101]";
  tk_102.level = lt_102.u "level [IR tk_102_lt_102]";
  lt_101.y = lt_101.u;
  lt_102.y = lt_102.u;
  pb_shut.table.combiTimeTable.timeScaled = time;
  when {time >= pre(pb_shut.table.combiTimeTable.nextTimeEvent), initial()} then
    pb_shut.table.combiTimeTable.nextTimeEventScaled = Modelica.Blocks.Tables.Internal.getNextTimeEvent(pb_shut.table.combiTimeTable.tableID, pb_shut.table.combiTimeTable.timeScaled);
    pb_shut.table.combiTimeTable.nextTimeEvent = if pb_shut.table.combiTimeTable.nextTimeEventScaled < 1e60 then pb_shut.table.combiTimeTable.nextTimeEventScaled else 1e60;
  end when;
  pb_shut.table.combiTimeTable.y[1] = pb_shut.table.combiTimeTable.p_offset[1] + Modelica.Blocks.Tables.Internal.getTimeTableValueNoDer(pb_shut.table.combiTimeTable.tableID, 1, pb_shut.table.combiTimeTable.timeScaled, pb_shut.table.combiTimeTable.nextTimeEventScaled, pre(pb_shut.table.combiTimeTable.nextTimeEventScaled));
  pb_shut.table.realToBoolean.y = pb_shut.table.realToBoolean.u >= pb_shut.table.realToBoolean.threshold;
  pb_shut.y = pb_shut.table.y;
  pb_start.table.combiTimeTable.timeScaled = time;
  when {time >= pre(pb_start.table.combiTimeTable.nextTimeEvent), initial()} then
    pb_start.table.combiTimeTable.nextTimeEventScaled = Modelica.Blocks.Tables.Internal.getNextTimeEvent(pb_start.table.combiTimeTable.tableID, pb_start.table.combiTimeTable.timeScaled);
    pb_start.table.combiTimeTable.nextTimeEvent = if pb_start.table.combiTimeTable.nextTimeEventScaled < 1e60 then pb_start.table.combiTimeTable.nextTimeEventScaled else 1e60;
  end when;
  pb_start.table.combiTimeTable.y[1] = pb_start.table.combiTimeTable.p_offset[1] + Modelica.Blocks.Tables.Internal.getTimeTableValueNoDer(pb_start.table.combiTimeTable.tableID, 1, pb_start.table.combiTimeTable.timeScaled, pb_start.table.combiTimeTable.nextTimeEventScaled, pre(pb_start.table.combiTimeTable.nextTimeEventScaled));
  pb_start.table.realToBoolean.y = pb_start.table.realToBoolean.u >= pb_start.table.realToBoolean.threshold;
  pb_start.y = pb_start.table.y;
  pb_stop.table.combiTimeTable.timeScaled = time;
  when {time >= pre(pb_stop.table.combiTimeTable.nextTimeEvent), initial()} then
    pb_stop.table.combiTimeTable.nextTimeEventScaled = Modelica.Blocks.Tables.Internal.getNextTimeEvent(pb_stop.table.combiTimeTable.tableID, pb_stop.table.combiTimeTable.timeScaled);
    pb_stop.table.combiTimeTable.nextTimeEvent = if pb_stop.table.combiTimeTable.nextTimeEventScaled < 1e60 then pb_stop.table.combiTimeTable.nextTimeEventScaled else 1e60;
  end when;
  pb_stop.table.combiTimeTable.y[1] = pb_stop.table.combiTimeTable.p_offset[1] + Modelica.Blocks.Tables.Internal.getTimeTableValueNoDer(pb_stop.table.combiTimeTable.tableID, 1, pb_stop.table.combiTimeTable.timeScaled, pb_stop.table.combiTimeTable.nextTimeEventScaled, pre(pb_stop.table.combiTimeTable.nextTimeEventScaled));
  pb_stop.table.realToBoolean.y = pb_stop.table.realToBoolean.u >= pb_stop.table.realToBoolean.threshold;
  pb_stop.y = pb_stop.table.y;
  plc_101.valve1 = plc_101.state == plc_101.State.fill_t1;
  plc_101.valve2 = plc_101.state == plc_101.State.transfer_t1_t2 or plc_101.state == plc_101.State.shutdown;
  plc_101.valve3 = plc_101.state == plc_101.State.drain_t2 or plc_101.state == plc_101.State.shutdown;
  assert(not (plc_101.valve1 and plc_101.valve2) and (not (plc_101.valve2 and plc_101.valve3) or plc_101.state == plc_101.State.shutdown), "ac_08: Normal automatic operation shall never command V1 and V2 simultaneously, nor V2 and V3 simultaneously. The latter combination is permitted only in SHUTDOWN.");
  der(tk_101.h) = (tk_101.inlet - tk_101.outlet) / tk_101.A;
  tk_101.level = tk_101.h;
  der(tk_102.h) = (tk_102.inlet - tk_102.outlet) / tk_102.A;
  tk_102.level = tk_102.h;
  xv_101.outlet = if xv_101.open then xv_101.q_nominal else 0.0;
  xv_101.inlet = xv_101.outlet;
  xv_102.outlet = if xv_102.open then xv_102.q_nominal else 0.0;
  xv_102.inlet = xv_102.outlet;
  xv_103.outlet = if xv_103.open then xv_103.q_nominal else 0.0;
  xv_103.inlet = xv_103.outlet;
algorithm
  when {edge(plc_101.start), edge(plc_101.stop), edge(plc_101.shut), pre(plc_101.state) == plc_101.State.fill_t1 and plc_101.level1 >= plc_101.tk_101_high_level, pre(plc_101.state) == plc_101.State.wait_after_fill and time >= plc_101.wait_after_fill_timer_deadline, pre(plc_101.state) == plc_101.State.transfer_t1_t2 and plc_101.level1 <= plc_101.tk_101_low_level, pre(plc_101.state) == plc_101.State.wait_after_transfer and time >= plc_101.wait_after_transfer_timer_deadline, pre(plc_101.state) == plc_101.State.drain_t2 and plc_101.level2 <= plc_101.tk_102_low_level, pre(plc_101.state) == plc_101.State.wait_after_drain and time >= plc_101.wait_after_drain_timer_deadline, pre(plc_101.state) == plc_101.State.shutdown and plc_101.level1 <= plc_101.tk_101_low_level and plc_101.level2 <= plc_101.tk_102_low_level} then
    if pre(plc_101.state) == plc_101.State.idle then
      if edge(plc_101.shut) then
        plc_101.history_state := plc_101.State.idle;
        plc_101.state := plc_101.State.shutdown;
      elseif edge(plc_101.start) then
        plc_101.state := plc_101.State.fill_t1;
      end if;
    elseif pre(plc_101.state) == plc_101.State.fill_t1 then
      if edge(plc_101.shut) then
        plc_101.history_state := plc_101.State.idle;
        plc_101.state := plc_101.State.shutdown;
      elseif edge(plc_101.stop) then
        plc_101.history_state := plc_101.State.fill_t1;
        plc_101.state := plc_101.State.paused;
      elseif plc_101.level1 >= plc_101.tk_101_high_level then
        plc_101.wait_after_fill_timer_deadline := time + plc_101.plc_101_wait_after_fill;
        plc_101.state := plc_101.State.wait_after_fill;
      end if;
    elseif pre(plc_101.state) == plc_101.State.wait_after_fill then
      if edge(plc_101.shut) then
        plc_101.history_state := plc_101.State.idle;
        plc_101.state := plc_101.State.shutdown;
      elseif edge(plc_101.stop) then
        plc_101.history_state := plc_101.State.wait_after_fill;
        plc_101.wait_after_fill_timer_remaining := plc_101.wait_after_fill_timer_deadline - time;
        plc_101.state := plc_101.State.paused;
      elseif time >= plc_101.wait_after_fill_timer_deadline then
        plc_101.state := plc_101.State.transfer_t1_t2;
      end if;
    elseif pre(plc_101.state) == plc_101.State.transfer_t1_t2 then
      if edge(plc_101.shut) then
        plc_101.history_state := plc_101.State.idle;
        plc_101.state := plc_101.State.shutdown;
      elseif edge(plc_101.stop) then
        plc_101.history_state := plc_101.State.transfer_t1_t2;
        plc_101.state := plc_101.State.paused;
      elseif plc_101.level1 <= plc_101.tk_101_low_level then
        plc_101.wait_after_transfer_timer_deadline := time + plc_101.plc_101_wait_after_transfer;
        plc_101.state := plc_101.State.wait_after_transfer;
      end if;
    elseif pre(plc_101.state) == plc_101.State.wait_after_transfer then
      if edge(plc_101.shut) then
        plc_101.history_state := plc_101.State.idle;
        plc_101.state := plc_101.State.shutdown;
      elseif edge(plc_101.stop) then
        plc_101.history_state := plc_101.State.wait_after_transfer;
        plc_101.wait_after_transfer_timer_remaining := plc_101.wait_after_transfer_timer_deadline - time;
        plc_101.state := plc_101.State.paused;
      elseif time >= plc_101.wait_after_transfer_timer_deadline then
        plc_101.state := plc_101.State.drain_t2;
      end if;
    elseif pre(plc_101.state) == plc_101.State.drain_t2 then
      if edge(plc_101.shut) then
        plc_101.history_state := plc_101.State.idle;
        plc_101.state := plc_101.State.shutdown;
      elseif edge(plc_101.stop) then
        plc_101.history_state := plc_101.State.drain_t2;
        plc_101.state := plc_101.State.paused;
      elseif plc_101.level2 <= plc_101.tk_102_low_level then
        plc_101.wait_after_drain_timer_deadline := time + plc_101.plc_101_wait_after_drain;
        plc_101.state := plc_101.State.wait_after_drain;
      end if;
    elseif pre(plc_101.state) == plc_101.State.wait_after_drain then
      if edge(plc_101.shut) then
        plc_101.history_state := plc_101.State.idle;
        plc_101.state := plc_101.State.shutdown;
      elseif edge(plc_101.stop) then
        plc_101.history_state := plc_101.State.wait_after_drain;
        plc_101.wait_after_drain_timer_remaining := plc_101.wait_after_drain_timer_deadline - time;
        plc_101.state := plc_101.State.paused;
      elseif time >= plc_101.wait_after_drain_timer_deadline then
        plc_101.state := plc_101.State.fill_t1;
      end if;
    elseif pre(plc_101.state) == plc_101.State.paused then
      if edge(plc_101.shut) then
        plc_101.history_state := plc_101.State.idle;
        plc_101.state := plc_101.State.shutdown;
      elseif edge(plc_101.start) then
        plc_101.state := plc_101.history_state;
        if plc_101.history_state == plc_101.State.wait_after_fill then
          plc_101.wait_after_fill_timer_deadline := time + plc_101.wait_after_fill_timer_remaining;
        end if;
        if plc_101.history_state == plc_101.State.wait_after_transfer then
          plc_101.wait_after_transfer_timer_deadline := time + plc_101.wait_after_transfer_timer_remaining;
        end if;
        if plc_101.history_state == plc_101.State.wait_after_drain then
          plc_101.wait_after_drain_timer_deadline := time + plc_101.wait_after_drain_timer_remaining;
        end if;
      end if;
    elseif pre(plc_101.state) == plc_101.State.shutdown then
      if plc_101.level1 <= plc_101.tk_101_low_level and plc_101.level2 <= plc_101.tk_102_low_level then
        plc_101.state := plc_101.State.idle;
      end if;
    end if;
  end when;
end two_tank_sequence.System;
