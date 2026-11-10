import { useState } from "react";
import * as path from "path";

export function topLevelFunction(x: number): number {
  path.join("a", "b");
  return useState(x);
}

export class Greeter {
  name: string;

  constructor(name: string) {
    this.name = name;
  }

  greet(): string {
    return helper(this.name);
  }
}

export const arrowHelper = (name: string): string => {
  return helper(name);
};

function helper(name: string): string {
  return `hello ${name}`;
}
