import { TypedFile } from "@/lib/connectors/fileTypes";

export type dictionaryType = Record<string, string | TypedFile>;
export interface formType extends dictionaryType {
  name: string;
}

export type ActionType = "create" | "createAndSwap";
