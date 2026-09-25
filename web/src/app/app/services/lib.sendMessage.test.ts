import { sendMessage, type SendMessageParams } from "@/app/app/services/lib";

// The request body sendMessage posts. The mocked response fails so the
// generator stops right after the request.
async function postedBody(
  params: Partial<SendMessageParams>
): Promise<Record<string, unknown>> {
  const fetchMock = jest.fn().mockResolvedValue({
    ok: false,
    status: 500,
    json: async () => ({ detail: "stop" }),
  });
  global.fetch = fetchMock;
  await expect(
    sendMessage({
      message: "Name one color.",
      parentMessageId: 253,
      chatSessionId: "session-1",
      filters: null,
      ...params,
    }).next()
  ).rejects.toThrow("stop");
  return JSON.parse(fetchMock.mock.calls[0]![1].body);
}

describe("sendMessage payload", () => {
  it("names a single-model reply by the model's display name", async () => {
    const body = await postedBody({
      modelProvider: "bedrock",
      modelVersion: "us.anthropic.claude-opus-5-5",
      modelConfigurationId: 7,
      modelDisplayName: "Claude Opus 5.5 (us)",
      regenerate: false,
    });

    expect(body.llm_override).toEqual({
      model_provider: "bedrock",
      model_version: "us.anthropic.claude-opus-5-5",
      model_configuration_id: 7,
      display_name: "Claude Opus 5.5 (us)",
    });
    expect(body.regenerate).toBe(false);
  });

  it("leaves the display name out when it is unknown", async () => {
    const body = await postedBody({ modelVersion: "custom-model" });

    expect(body.llm_override).not.toHaveProperty("display_name");
    expect(body.regenerate).toBeNull();
  });
});
