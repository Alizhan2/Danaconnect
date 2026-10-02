export type Material = {
  id: string;
  direction_id: string | null;
  title: string;
  description: string;
  text_locale: "ru" | "kk" | "en";
  url: string;
  kind: string;
  content_language: string;
  active: boolean;
  updated_at: string;
  title_ru?: string;
  title_kk?: string;
  title_en?: string;
  description_ru?: string;
  description_kk?: string;
  description_en?: string;
};
export type Award = {
  id: string;
  user_id?: string;
  issued_name?: string;
  kind: string;
  title: string;
  description: string;
  text_locale: string;
  result_id: string | null;
  issued_at: string;
  revoked_at: string | null;
  revocation_reason: string | null;
  certificate_available: boolean;
};
export type Preference = {
  visible: boolean;
  alias: string;
  consent_version: string | null;
  required_version: string;
  terms: string;
};
export type AchievementData = {
  points: number;
  counts: Record<string, number>;
  badges: {
    code: string;
    title: string;
    earned: boolean;
    progress: number;
    threshold: number;
    source_type: string;
  }[];
  rules: Record<string, number>;
  events: {
    id: string;
    source_type: string;
    points: number;
    earned_at: string;
  }[];
  awards: Award[];
  leaderboard_preference: Preference;
  demo_mode: boolean;
};
export type Leaderboard = {
  entries: { rank: number; alias: string; points: number; badges: string[] }[];
  demo_mode: boolean;
};
export type Portfolio = {
  visibility: string;
  results: {
    id: string;
    summary: string;
    artifact_url: string | null;
    completed_at: string;
    meeting_count: number;
  }[];
};
