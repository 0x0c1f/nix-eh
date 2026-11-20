# For configurations that already supply their own Nixpkgs.
{ pkgs ? import <nixpkgs> { } }:
# Use the caller's package set, including its overlays, rather than creating
# a second Nixpkgs instance just to package the diagnostic reader.
pkgs.callPackage ./package.nix { }
