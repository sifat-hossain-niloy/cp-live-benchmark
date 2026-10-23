import { describe, expect, it } from "vitest";
import { bootstrap, fitSkill, probability, selectIds } from "./scoring";
import type { Dataset, Filters } from "./types";

describe("scientific scoring", () => {
  it("matches the Python bootstrap exactly", () => {
    const outcomes = Array.from({ length: 20 }, (_, i) => ({
      id: String(i),
      rating: 800 + i * 100,
      accepted: (i * 7) % 5,
      samples: 4,
    }));
    expect(fitSkill(outcomes)).toBeCloseTo(1750, 8);
    const ci = bootstrap(outcomes);
    expect(ci.low).toBeCloseTo(1279.5364886858024, 8);
    expect(ci.high).toBeCloseTo(2205.673509821605, 8);
  });
  it("has the expected logistic midpoint", () =>
    expect(probability(1600, 1600)).toBe(0.5));
  it("fits balanced evidence and refuses saturated estimates", () => {
    expect(
      fitSkill([{ id: "a", rating: 1600, accepted: 2, samples: 4 }]),
    ).toBeCloseTo(1600, 7);
    expect(
      fitSkill([{ id: "a", rating: 1600, accepted: 0, samples: 4 }]),
    ).toBeNull();
  });
  it("bootstraps whole problems with unbounded extremes", () => {
    const ci = bootstrap([
      { id: "a", rating: 1200, accepted: 0, samples: 4 },
      { id: "b", rating: 1600, accepted: 4, samples: 4 },
    ]);
    expect(ci.unbounded_low).toBe(true);
    expect(ci.unbounded_high).toBe(true);
  });
  it("uses the intersection after the entire latest cutoff day", () => {
    const data = {
      models: [
        {
          name: "a",
          training_cutoff: "2025-01-01",
          scored_problem_ids: ["p", "q", "r"],
        },
        {
          name: "b",
          training_cutoff: "2025-02-01",
          scored_problem_ids: ["q", "r"],
        },
      ],
      problems: [
        { id: "p", contest_date: "2025-01-20" },
        { id: "q", contest_date: "2025-02-01" },
        { id: "r", contest_date: "2025-02-02" },
      ].map((p) => ({
        ...p,
        verified: true,
        rating: 1200,
        tags: ["math"],
        division: "Div. 2",
      })),
    } as Dataset;
    const filters: Filters = {
      common: true,
      since: "",
      rating: "",
      tag: "",
      division: "",
      models: ["a", "b"],
    };
    expect([...selectIds(data, filters).get("a")!]).toEqual(["r"]);
    expect([...selectIds(data, filters).get("b")!]).toEqual(["r"]);
  });
});
