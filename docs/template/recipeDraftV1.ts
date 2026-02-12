import { z } from "zod";

const FORBIDDEN_ORDER_KEYS = new Set(["step_number", "line_order"]);
const StagingIdSchema = z.string().trim().min(1, "Value is required");

type PathSegment = string | number;

const IngredientLineStagingSchema = z
  .object({
    ingredient_id: StagingIdSchema.optional().nullable(),
    linked_recipe_id: StagingIdSchema.optional().nullable(),
    quantity_kind: z.enum(["exact", "approximate", "unquantified"]),
    input_qty: z.number().positive().optional().nullable(),
    input_unit_id: StagingIdSchema.optional().nullable(),
    note: z.string().optional().nullable(),
    preparation: z.string().optional().nullable(),
    raw_text: z.string().optional().nullable(),
    confidence: z.number().min(0).max(1).optional().nullable(),
    raw_unit_text: z.string().optional().nullable(),
    raw_ingredient_text: z.string().optional().nullable(),
    is_optional: z.boolean().optional().default(false),
  })
  .strict()
  .superRefine((value, ctx) => {
    const hasIngredient =
      value.ingredient_id !== null && value.ingredient_id !== undefined;
    const hasLinkedRecipe =
      value.linked_recipe_id !== null && value.linked_recipe_id !== undefined;

    if (!hasIngredient && !hasLinkedRecipe) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["ingredient_id"],
        message: "Either ingredient_id or linked_recipe_id must be set.",
      });
      return;
    }

    if (hasIngredient && hasLinkedRecipe) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["linked_recipe_id"],
        message: "Cannot set both ingredient_id and linked_recipe_id.",
      });
      return;
    }

    if (hasLinkedRecipe) {
      const hasQty = value.input_qty !== null && value.input_qty !== undefined;
      if (hasQty && value.input_qty! <= 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_qty"],
          message: "Batch multiplier must be positive.",
        });
      }
      if (hasQty && value.input_qty! > 100) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_qty"],
          message: "Batch multiplier cannot exceed 100.",
        });
      }
      if (value.input_unit_id !== null && value.input_unit_id !== undefined) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_unit_id"],
          message: "input_unit_id should not be set for recipe lines.",
        });
      }
      return;
    }

    const hasQty = value.input_qty !== null && value.input_qty !== undefined;
    const hasUnit =
      value.input_unit_id !== null && value.input_unit_id !== undefined;

    if (value.quantity_kind === "unquantified") {
      if (hasQty) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_qty"],
          message: "input_qty must be null or omitted for unquantified lines.",
        });
      }
      if (hasUnit) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_unit_id"],
          message:
            "input_unit_id must be null or omitted for unquantified lines.",
        });
      }
      return;
    }

    if (!hasQty) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["input_qty"],
        message: "input_qty is required for exact or approximate lines.",
      });
    }
  });

const StepSchema = z
  .object({
    instruction: z.string().trim().min(1),
    ingredient_lines: z.array(IngredientLineStagingSchema),
    time_seconds: z.number().nonnegative().optional().nullable(),
    temperature: z.number().optional().nullable(),
    temperature_unit: z.string().trim().min(1).optional().nullable(),
  })
  .strict();

const RecipeSchema = z
  .object({
    confidence: z.number().min(0).max(1).optional().nullable(),
    cook_time_seconds: z.number().nonnegative().optional().nullable(),
    title: z.string().trim().min(1),
    description: z.string().optional().nullable(),
    notes: z.string().optional().nullable(),
    image_url: z.string().optional().nullable(),
    variants: z.array(z.string().trim().min(1)).optional().nullable(),
    yield_units: z.number().min(1).optional().default(1),
    yield_phrase: z.string().optional().nullable(),
    yield_unit_name: z.string().optional().nullable(),
    yield_detail: z.string().optional().nullable(),
  })
  .strict();

export const RecipeDraftV1Schema = z
  .object({
    schema_v: z.literal(1),
    source: z.string().trim().min(1).optional().nullable(),
    recipe: RecipeSchema,
    steps: z.array(StepSchema).min(1),
  })
  .strict()
  .superRefine((value, ctx) => {
    const hits: { path: PathSegment[]; key: string }[] = [];

    const scan = (current: unknown, path: PathSegment[]) => {
      if (Array.isArray(current)) {
        current.forEach((item, index) => scan(item, [...path, index]));
        return;
      }

      if (current && typeof current === "object") {
        for (const [key, child] of Object.entries(
          current as Record<string, unknown>,
        )) {
          if (FORBIDDEN_ORDER_KEYS.has(key)) {
            hits.push({ path: [...path, key], key });
          }
          scan(child, [...path, key]);
        }
      }
    };

    scan(value, []);

    hits.forEach((hit) => {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: hit.path,
        message: `${hit.key} is server-derived and must not appear in drafts.`,
      });
    });
  });

export type RecipeDraftV1 = z.infer<typeof RecipeDraftV1Schema>;

export function parseRecipeDraftV1(input: unknown): RecipeDraftV1 {
  if (input && typeof input === "object" && "steps" in input) {
    const obj = input as { steps?: unknown };
    if (Array.isArray(obj.steps)) {
      obj.steps = obj.steps.filter(
        (step): step is object => step !== null && step !== undefined,
      );
    }
  }

  return RecipeDraftV1Schema.parse(input);
}

export function formatZodError(err: unknown): string {
  if (err instanceof z.ZodError) {
    return err.issues
      .map((issue) => {
        const path = issue.path.length ? issue.path.join(".") : "input";
        return `${path}: ${issue.message}`;
      })
      .join("\n");
  }

  if (err instanceof Error) {
    return err.message;
  }

  return "Unknown validation error.";
}
