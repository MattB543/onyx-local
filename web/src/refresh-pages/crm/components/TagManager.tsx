"use client";

import { useEffect, useMemo, useState } from "react";

import {
  addTagToContact,
  addTagToOrganization,
  createCrmTag,
  CrmTag,
  listCrmTags,
  removeTagFromContact,
  removeTagFromOrganization,
} from "@/app/app/crm/crmService";
import { cn } from "@/lib/utils";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Popover from "@/refresh-components/Popover";
import Text from "@/refresh-components/texts/Text";

import { SvgPlus, SvgTag, SvgX } from "@opal/icons";

interface TagManagerProps {
  entityType: "contact" | "organization";
  entityId: string;
  tags: CrmTag[];
  onRefresh: () => void;
  showLabel?: boolean;
}

export default function TagManager({
  entityType,
  entityId,
  tags,
  onRefresh,
  showLabel = true,
}: TagManagerProps) {
  const [open, setOpen] = useState(false);
  const [allTags, setAllTags] = useState<CrmTag[]>([]);
  const [tagSearch, setTagSearch] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }

    void listCrmTags({ page_size: 100 })
      .then((result) => setAllTags(result.items))
      .catch(() => {});
  }, [open]);

  const currentTagIds = useMemo(
    () => new Set(tags.map((tag) => tag.id)),
    [tags]
  );
  const availableTags = allTags.filter(
    (tag) =>
      !currentTagIds.has(tag.id) &&
      tag.name.toLowerCase().includes(tagSearch.toLowerCase())
  );
  const canCreateNew =
    tagSearch.trim().length > 0 &&
    !allTags.some(
      (tag) => tag.name.toLowerCase() === tagSearch.trim().toLowerCase()
    );

  async function handleAddTag(tagId: string) {
    try {
      if (entityType === "contact") {
        await addTagToContact(entityId, tagId);
      } else {
        await addTagToOrganization(entityId, tagId);
      }
      onRefresh();
    } catch {
      // silently fail
    }
  }

  async function handleRemoveTag(tagId: string) {
    try {
      if (entityType === "contact") {
        await removeTagFromContact(entityId, tagId);
      } else {
        await removeTagFromOrganization(entityId, tagId);
      }
      onRefresh();
    } catch {
      // silently fail
    }
  }

  async function handleCreateAndAddTag() {
    if (!canCreateNew || isCreating) {
      return;
    }

    setIsCreating(true);
    try {
      const newTag = await createCrmTag({ name: tagSearch.trim() });
      await handleAddTag(newTag.id);
      setTagSearch("");
      const result = await listCrmTags({ page_size: 100 });
      setAllTags(result.items);
    } catch {
      // silently fail
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {showLabel && (
        <Text as="p" mainUiAction text02>
          Tags
        </Text>
      )}

      <div className="flex flex-wrap items-center gap-1.5">
        {tags.map((tag) => (
          <span
            key={tag.id}
            className="inline-flex items-center gap-1 rounded-full bg-background-tint-02 px-2 py-0.5"
          >
            <SvgTag size={10} className="stroke-text-03" />
            <Text as="span" figureSmallLabel text02 className="text-sm">
              {tag.name}
            </Text>
            <button
              type="button"
              onClick={() => handleRemoveTag(tag.id)}
              className="ml-0.5 rounded-full p-0.5 hover:bg-background-tint-03"
            >
              <SvgX size={10} className="stroke-text-03" />
            </button>
          </span>
        ))}

        <Popover open={open} onOpenChange={setOpen}>
          <Popover.Trigger asChild>
            <button
              type="button"
              className={cn(
                "inline-flex items-center gap-1 rounded-full border border-dashed border-border-subtle px-2 py-0.5",
                "transition-colors hover:bg-background-tint-02"
              )}
            >
              <SvgPlus size={10} className="stroke-text-03" />
              <Text as="span" figureSmallLabel text02 className="text-sm">
                Add tag
              </Text>
            </button>
          </Popover.Trigger>

          <Popover.Content
            align="start"
            side="bottom"
            width="xl"
            sideOffset={8}
          >
            <div className="flex w-full flex-col gap-2 p-1">
              <InputTypeIn
                value={tagSearch}
                onChange={(event) => setTagSearch(event.target.value)}
                placeholder="Search or create tag..."
                leftSearchIcon
                autoFocus
              />

              <div className="flex max-h-[14rem] flex-col gap-0.5 overflow-y-auto">
                {availableTags.map((tag) => (
                  <button
                    key={tag.id}
                    type="button"
                    onClick={() => {
                      void handleAddTag(tag.id);
                      setOpen(false);
                      setTagSearch("");
                    }}
                    className="rounded px-2 py-1 text-left text-sm hover:bg-background-tint-02"
                  >
                    {tag.name}
                  </button>
                ))}

                {availableTags.length === 0 && !canCreateNew && (
                  <Text
                    as="p"
                    secondaryBody
                    text03
                    className="px-2 py-1 text-sm italic"
                  >
                    No matching tags
                  </Text>
                )}

                {canCreateNew && (
                  <button
                    type="button"
                    onClick={() => {
                      void handleCreateAndAddTag();
                    }}
                    disabled={isCreating}
                    className="rounded px-2 py-1 text-left text-sm font-medium text-text-04 hover:bg-background-tint-02"
                  >
                    {isCreating
                      ? "Creating..."
                      : `Create "${tagSearch.trim()}"`}
                  </button>
                )}
              </div>

              <div className="flex justify-end">
                <Button
                  action
                  tertiary
                  size="md"
                  onClick={() => setOpen(false)}
                >
                  Done
                </Button>
              </div>
            </div>
          </Popover.Content>
        </Popover>
      </div>
    </div>
  );
}
