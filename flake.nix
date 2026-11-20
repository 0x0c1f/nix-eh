{
  description = "nix-eh: readable Nix diagnostics";

  # The channel tarball is much smaller to fetch than a full nixpkgs Git clone.
  inputs.nixpkgs.url = "tarball+https://channels.nixos.org/nixpkgs-unstable/nixexprs.tar.zst";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      pkgsFor = system: import nixpkgs {
        inherit system;
      };
      packageFor = system: (pkgsFor system).callPackage ./package.nix { };
    in
    {
      packages = forAllSystems (system: rec {
        nix-eh = packageFor system;
        default = nix-eh;
      });
      apps = forAllSystems (system: rec {
        nix-eh = {
          type = "app";
          program = "${packageFor system}/bin/nix-eh";
        };
        default = nix-eh;
      });
      checks = forAllSystems (system:
        let
          pkgs = pkgsFor system;
          package = packageFor system;
        in
        {
          # Run the unit tests from a writable copy; files in the Nix store are
          # read-only, so tests cannot run in place.
          diagnostics = pkgs.runCommand "nix-eh-diagnostics"
            {
              nativeBuildInputs = [ pkgs.python3 ];
              src = pkgs.lib.cleanSource ./.;
            } ''
            cp -r "$src" source
            chmod -R u+w source
            cd source
            python3 -B -m unittest -v
            touch "$out"
          '';
          cli = pkgs.runCommand "nix-eh-cli"
            {
              nativeBuildInputs = [ package pkgs.python3 ];
            } ''
            # Check the installed command, not the source tree: these assertions
            # catch packaging mistakes that the unit tests cannot see.
            nix-eh --json read ${./examples/insecure-electron.log} > report.json
            python3 -c 'import json; d=json.load(open("report.json")); assert d["package"] == "electron-36.9.5"; assert "NIXPKGS_ALLOW_INSECURE=1" in d["original"]'

            # A wrapped failure must keep the original exit status; scripts that
            # branch on Nix failures would otherwise break when nix-eh is enabled.
            set +e
            nix-eh run -- python3 -c 'import sys; print("error: test failure", file=sys.stderr); sys.exit(7)' 2> diagnostic.txt
            status=$?
            set -e
            test "$status" -eq 7
            grep -q 'test failure' diagnostic.txt
            touch "$out"
          '';
        });
    };
}
