/** Evaluate a syntax tree against a set of variables. */

import type { Node } from "./parser.ts";

/** A value of the language. */
export type Value = number | string | boolean | null | Value[] | { [key: string]: Value };

/** A problem found while evaluating (a missing name, a wrong type, a division by zero). */
export class EvalError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EvalError";
  }
}

function truthy(value: Value): boolean {
  return value !== null && value !== false && value !== 0 && value !== "";
}

function numbers(op: string, left: Value, right: Value): [number, number] {
  if (typeof left !== "number" || typeof right !== "number") {
    throw new EvalError(`"${op}" needs two numbers`);
  }
  return [left, right];
}

function same(left: Value, right: Value): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/** Evaluate `node`; `variables` holds the names an expression may use. */
export function evaluate(node: Node, variables: Readonly<Record<string, Value>>): Value {
  switch (node.type) {
    case "number":
    case "string":
    case "literal":
      return node.value;
    case "name": {
      if (!(node.name in variables)) {
        throw new EvalError(`unknown name "${node.name}"`);
      }
      return variables[node.name];
    }
    case "member": {
      const object = evaluate(node.object, variables);
      if (typeof object !== "object" || object === null || Array.isArray(object) || !(node.name in object)) {
        throw new EvalError(`no field "${node.name}"`);
      }
      return object[node.name];
    }
    case "index": {
      const object = evaluate(node.object, variables);
      const index = evaluate(node.index, variables);
      if (!Array.isArray(object) || typeof index !== "number" || !Number.isInteger(index)) {
        throw new EvalError("only a list can be indexed, by a whole number");
      }
      if (index < 0 || index >= object.length) {
        throw new EvalError(`index ${index} is outside the list`);
      }
      return object[index];
    }
    case "list":
      return node.items.map((item) => evaluate(item, variables));
    case "unary": {
      const operand = evaluate(node.operand, variables);
      if (node.op === "!") {
        return !truthy(operand);
      }
      if (typeof operand !== "number") {
        throw new EvalError('"-" needs a number');
      }
      return -operand;
    }
    case "conditional":
      return truthy(evaluate(node.test, variables)) ? evaluate(node.yes, variables) : evaluate(node.no, variables);
    case "binary":
      return binary(node.op, node.left, node.right, variables);
  }
}

function binary(op: string, leftNode: Node, rightNode: Node, variables: Readonly<Record<string, Value>>): Value {
  if (op === "&&" || op === "and") {
    const left = evaluate(leftNode, variables);
    return truthy(left) ? evaluate(rightNode, variables) : left;
  }
  if (op === "||" || op === "or") {
    const left = evaluate(leftNode, variables);
    return truthy(left) ? left : evaluate(rightNode, variables);
  }
  const left = evaluate(leftNode, variables);
  const right = evaluate(rightNode, variables);
  switch (op) {
    case "==":
      return same(left, right);
    case "!=":
      return !same(left, right);
    case "in":
      if (Array.isArray(right)) {
        return right.some((item) => same(item, left));
      }
      if (typeof right === "string" && typeof left === "string") {
        return right.includes(left);
      }
      throw new EvalError('"in" needs a list or a string on its right');
    case "+":
      if (typeof left === "string" && typeof right === "string") {
        return left + right;
      }
      return numbers(op, left, right).reduce((a, b) => a + b);
    case "-":
      return numbers(op, left, right).reduce((a, b) => a - b);
    case "*":
      return numbers(op, left, right).reduce((a, b) => a * b);
    case "/": {
      const [a, b] = numbers(op, left, right);
      if (b === 0) {
        throw new EvalError("division by zero");
      }
      return a / b;
    }
    case "%": {
      const [a, b] = numbers(op, left, right);
      if (b === 0) {
        throw new EvalError("division by zero");
      }
      return a % b;
    }
    case "**": {
      const [a, b] = numbers(op, left, right);
      return a ** b;
    }
    default: {
      const [a, b] = numbers(op, left, right);
      return op === "<" ? a < b : op === "<=" ? a <= b : op === ">" ? a > b : a >= b;
    }
  }
}
