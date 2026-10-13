class ScriptedProvider:
    """Return canned model text while retaining the actual rendered requests."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.contexts = []

    async def acall(self, context, *, tools=None, tool_results=None):
        self.contexts.append(context)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response, []
