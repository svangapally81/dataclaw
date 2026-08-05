import type { SimpleIcon } from "simple-icons";
import {
  siAirbyte,
  siAmazonredshift,
  siApacheairflow,
  siConfluence,
  siDatabricks,
  siDbt,
  siGithub,
  siGooglebigquery,
  siGoogledocs,
  siGoogledrive,
  siMysql,
  siNotion,
  siOpenai,
  siPostgresql,
  siPrefect,
  siQuip,
  siSnowflake,
  siSqlite,
} from "simple-icons";

export type LogoDefinition =
  | { kind: "asset"; src: string; title: string }
  | { kind: "simple"; icon: SimpleIcon };

export const LOGO_ASSETS: Record<string, string> = {
  "microsoft-sql-server": "/logos/sql-server.svg",
  dagster: "/logos/dagster.svg",
  fivetran: "/logos/fivetran.svg",
};

export const SIMPLE_LOGOS: Record<string, SimpleIcon> = {
  airbyte: siAirbyte,
  "amazon-redshift": siAmazonredshift,
  "apache-airflow": siApacheairflow,
  confluence: siConfluence,
  databricks: siDatabricks,
  dbt: siDbt,
  github: siGithub,
  "google-bigquery": siGooglebigquery,
  "google-docs": siGoogledocs,
  "google-drive": siGoogledrive,
  mysql: siMysql,
  notion: siNotion,
  openai: siOpenai,
  postgresql: siPostgresql,
  prefect: siPrefect,
  quip: siQuip,
  snowflake: siSnowflake,
  sqlite: siSqlite,
};

export function logoDefinition(logoKey?: string): LogoDefinition | null {
  if (!logoKey) return null;
  const asset = LOGO_ASSETS[logoKey];
  if (asset) return { kind: "asset", src: asset, title: logoKey };
  const icon = SIMPLE_LOGOS[logoKey];
  if (icon) return { kind: "simple", icon };
  return null;
}

export function logoAsset(logoKey?: string) {
  const logo = logoDefinition(logoKey);
  return logo?.kind === "asset" ? logo.src : null;
}
