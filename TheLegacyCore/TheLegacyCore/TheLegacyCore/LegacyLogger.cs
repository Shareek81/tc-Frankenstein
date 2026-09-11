var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

var logs = new[] {
    new { Timestamp = DateTime.Now, Source = "192.168.1.1", Event = "Login Attempt", Status = "Success" },
    new { Timestamp = DateTime.Now.AddSeconds(-5), Source = "45.33.22.11", Event = "SSH Connection", Status = "Failed" },
    new { Timestamp = DateTime.Now.AddSeconds(-10), Source = "10.0.0.5", Event = "File Access", Status = "Denied" }
};

app.MapGet("/api/raw-logs", () => logs);
app.Run();