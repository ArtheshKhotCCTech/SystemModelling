// Purpose: the catalogue's command_button kind: a momentary press is true for one pulse width from
// each press time, so a controller sees one rising edge per press.
model CommandButton "Momentary pushbutton: true for one pulse width from each press time"
  parameter Real pressTimes[:](each unit = "s") = fill(0.0, 0) "Press times; none means never pressed";
  parameter Real width(unit = "s") = 1 "Pulse width of one press";
  SpecAlive.Interfaces.BooleanOutput y "True while pressed";
algorithm
  y := false;
  for i in 1:size(pressTimes, 1) loop
    if time >= pressTimes[i] and time < pressTimes[i] + width then
      y := true;
    end if;
  end for;
end CommandButton;
