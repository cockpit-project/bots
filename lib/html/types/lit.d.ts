/**
 * @license
 * Based on code copyright 2017 Google LLC
 * SPDX-License-Identifier: BSD-3-Clause
 */

declare module "lit" {
    export type CSSResultOrNative = CSSResult | CSSStyleSheet;
    export type CSSResultArray = Array<CSSResultOrNative | CSSResultArray>;
    export type CSSResultGroup = CSSResultOrNative | CSSResultArray;

    export class CSSResult {
        "_$cssResult$": boolean;
        readonly cssText: string;
        private _styleSheet?;
        private _strings;
        private constructor();
        get styleSheet(): CSSStyleSheet | undefined;
        toString(): string;
    }

    export const css: (strings: TemplateStringsArray, ...values: (CSSResultGroup | number)[]) => CSSResult;

    interface ComplexAttributeConverter<Type = unknown, TypeHint = unknown> {
        fromAttribute?(value: string | null, type?: TypeHint): Type;
        toAttribute?(value: Type, type?: TypeHint): unknown;
    }

    type AttributeConverter<Type = unknown, TypeHint = unknown> =
        | ComplexAttributeConverter<Type>
        | ((value: string | null, type?: TypeHint) => Type);

    export interface PropertyDeclaration<Type = unknown, TypeHint = unknown> {
        readonly state?: boolean;
        readonly attribute?: boolean | string;
        readonly type?: TypeHint;
        readonly converter?: AttributeConverter<Type, TypeHint>;
        readonly reflect?: boolean;
        hasChanged?(value: Type, oldValue: Type): boolean;
        readonly noAccessor?: boolean;
    }

    export interface PropertyDeclarations {
        readonly [key: string]: PropertyDeclaration;
    }

    type ResultType = 1 | 2 | 3;

    export type TemplateResult<T extends ResultType = ResultType> = {
        "_$litType$": T;
        strings: TemplateStringsArray;
        values: unknown[];
    };

    export const html: (strings: TemplateStringsArray, ...values: unknown[]) => TemplateResult<1>;

    export const nothing: unique symbol;

    type KeyFn<T> = (item: T, index: number) => unknown;
    type ItemTemplate<T> = (item: T, index: number) => unknown;

    export interface RepeatDirectiveFn {
        <T>(items: Iterable<T>, keyFnOrTemplate: KeyFn<T> | ItemTemplate<T>, template?: ItemTemplate<T>): unknown;
        <T>(items: Iterable<T>, template: ItemTemplate<T>): unknown;
        <T>(items: Iterable<T>, keyFn: KeyFn<T> | ItemTemplate<T>, template: ItemTemplate<T>): unknown;
    }

    export const repeat: RepeatDirectiveFn;

    export class LitElement extends HTMLElement {
        static properties: PropertyDeclarations;
        static styles?: CSSResultGroup;
        connectedCallback(): void;
        disconnectedCallback(): void;
        protected createRenderRoot(): HTMLElement | DocumentFragment;
        requestUpdate(
            name?: PropertyKey,
            oldValue?: unknown,
            options?: PropertyDeclaration,
            useNewValue?: boolean,
            newValue?: unknown,
        ): void;
        protected render(): unknown;
    }
}
