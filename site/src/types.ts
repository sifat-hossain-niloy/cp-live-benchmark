export type Problem = {
  id: string;
  contest_id: number;
  index: string;
  name: string;
  rating: number;
  tags: string[];
  division: string;
  contest_date: string;
  contest_start: number;
  url: string;
  verified: boolean;
  statement_cached: boolean;
};
export type Model = {
  name: string;
  display_name: string;
  provider: string;
  model_id: string;
  training_cutoff: string;
  cutoff_source_url: string;
  release_date: string;
  eligible_problem_ids: string[];
  scored_problem_ids: string[];
  samples_per_problem: number;
  run_id: string;
  run_date: string;
  image_digest: string;
  compiler_versions: string;
  calibration_factor: number;
  sampling: Record<string, unknown>;
  language: string;
};
export type Result = {
  model_name: string;
  problem_id: string;
  sample_index: number;
  verdict: string;
  failing_category: string | null;
  cost_usd: number;
  cpu_ms: number;
  memory_kb: number;
  prompt_hash: string;
  run_id: string;
  judged_at: string;
  test_set_hash: string;
};
export type Dataset = {
  schema_version: number;
  generated_at: string;
  status: string;
  inventory: {
    collected_candidates: number;
    statements_cached: number;
    draft_directories: number;
    verified_problems: number;
    evaluated_models: number;
    configured_models: number;
  };
  models: Model[];
  problems: Problem[];
  results: Result[];
  model_configurations: {
    name: string;
    display_name: string;
    provider: string;
    ready: boolean;
    reason: string | null;
  }[];
};
export type Filters = {
  common: boolean;
  since: string;
  rating: string;
  tag: string;
  division: string;
  models: string[];
};
export type Outcome = {
  id: string;
  rating: number;
  accepted: number;
  samples: number;
};
export type CI = {
  low: number | null;
  high: number | null;
  unbounded_low: boolean;
  unbounded_high: boolean;
};
export type Score = {
  model: Model;
  pass1: number | null;
  rating: number | null;
  ci: CI;
  problems: number;
  eligible: number;
  samples: number;
  solved: number;
  cost: number;
  costPerSolved: number | null;
  insufficient: boolean;
  bands: Record<string, number>;
  tags: Record<string, number>;
  verdicts: Record<string, number>;
};
