# Record the README demo GIF with VHS (https://github.com/charmbracelet/vhs):
#   vhs demo/demo.tape
# Requires: doublecast installed, run from the repository root.

Output docs/demo.gif
Set FontSize 18
Set Width 1300
Set Height 720
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms

Hide
Type "export DOUBLECAST_HOME=$(mktemp -d) && cp examples/config.example.yaml $DOUBLECAST_HOME/config.yaml && cp examples/customers.csv $DOUBLECAST_HOME/ && clear"
Enter
Sleep 500ms
Show

Type "# What you would paste into an AI chat:"
Enter
Type `echo "Nordia Hellas wants 8% off invoice no. INV-2026/0418. Eleni Papadopoulou says the account is €1.234.567,89." > note.txt`
Enter
Sleep 800ms
Type "cat note.txt"
Enter
Sleep 1.5s

Type "# What the AI actually sees:"
Enter
Type "doublecast scramble - < note.txt | tee safe.txt"
Enter
Sleep 2.5s

Type "# And the AI's answer, restored on your machine:"
Enter
Type "doublecast restore - < safe.txt"
Enter
Sleep 3s
