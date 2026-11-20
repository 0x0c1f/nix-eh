# Package the diagnostic reader with its interpreter so wrappers do not rely
# on whichever Python happens to be on the user's PATH.

{ lib, writeShellApplication, python3 }:

writeShellApplication {
  name = "nix-eh";

  # Use an absolute interpreter: do not prepend Python to wrapped commands' PATH.
  text = ''
    exec ${python3}/bin/python3 -B ${./nix_eh.py} "$@"
  '';
  # Read release metadata into the derivation without changing the executable
  # wrapper: the command must still forward the original arguments unchanged.
  derivationArgs = {
    version = "0";
    meta = {
      description = "Readable summaries of Nix diagnostics";
      license = lib.licenses.gpl3Plus;
      mainProgram = "nix-eh";
      platforms = lib.platforms.unix;
    };
  };
}
