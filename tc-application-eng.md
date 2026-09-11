# **Technical Challenge: Application Engineer**

| Item | Details |
| :---- | :---- |
| **Internal Project Name** | Project Frankenstein’s Dashboard |
| **Time Limit** | 24 Hours |

---

## **1\. The Mission: “The Bridge Builder”**

Our legacy SaaS platform is reliable but visually static. In the current market, “static” doesn’t sell. To win over the next generation of CISO customers, we need to show—not just tell—how our software handles threats in real-time.

**Your Task:** You have 24 hours to bridge a legacy environment with a modern AI analytics engine to create a high-fidelity, interactive “Threat Command Center” demo.

**Principal’s Tip:**  
**Velocity \> Perfection.** We aren’t looking for hand-crafted, artisan loops. We are looking for a **Vibe Coder**—someone who uses AI orchestration (Cursor, v0.dev, Claude, etc.) to handle the boilerplate so they can focus on the “Theatrics” and the “Architecture.”

---

## **2\. The Legacy Core (ASP.NET)**

This represents our “old” backend. It generates raw, unorganized JSON logs of network activity. You must ingest this data.

C\#

```

// Save as LegacyLogger.cs
// This is a Minimal API representing our existing infrastructure.
var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

var logs = new[] {
    new { Timestamp = DateTime.Now, Source = "192.168.1.1", Event = "Login Attempt", Status = "Success" },
    new { Timestamp = DateTime.Now.AddSeconds(-5), Source = "45.33.22.11", Event = "SSH Connection", Status = "Failed" },
    new { Timestamp = DateTime.Now.AddSeconds(-10), Source = "10.0.0.5", Event = "File Access", Status = "Denied" }
};

app.MapGet("/api/raw-logs", () => logs);
app.Run();

```

---

## **3\. The Chaos Monkey (PowerShell)**

As a Demo Engineer, you must create “action” on the screen. Run this script to simulate a live cyber attack against your local environment. Your final dashboard must react to this file in real-time.

PowerShell

```

# Save as AttackSim.ps1
Write-Host "Starting Cyber Attack Simulation..." -ForegroundColor Red
while($true) {
    $attackTypes = "Brute Force", "SQL Injection", "Port Scan", "Credential Stuffing"
    $randomAttack = $attackTypes | Get-Random
    $severity = (Get-Random -Minimum 1 -Maximum 10)
    
    $logEntry = @{
        time = Get-Date -Format "HH:mm:ss"
        type = $randomAttack
        severity = $severity
        origin = "103.25.12.$(Get-Random -Minimum 1 -Maximum 255)"
    }
    
    $logEntry | ConvertTo-Json -Compress | Out-File -FilePath "./live_stream.log" -Append
    Write-Host "Generated Threat: $randomAttack (Severity: $severity)" -ForegroundColor Yellow
    Start-Sleep -Seconds (Get-Random -Minimum 1 -Maximum 3)
}

```

---

## **4\. Deliverables**

To pass the “Vibe Check,” your submission must include:

1. **The Analytics Bridge (Python):** A service that watches live\_stream.log and the LegacyLogger API. It must “score” the danger of each event (using a simple script or an LLM prompt).  
2. **The Command Center (HTML5/JS):** A dark-mode, “Hacker-Chic” dashboard.  
   * **Live Feed:** Real-time updates of incoming threats.  
   * **Visual Impact:** A global threat level gauge that turns red when the PowerShell script generates high-severity hits.  
3. **The “Sales” Edge:** Add one feature that would make a customer’s jaw drop.  
   * *Examples:* An “AI Summary” of the current attack, a “Mitigate” button that stops the PowerShell script, or a 3D map visualization.
4. **Public Repository:** Please include a link to a public GitHub repository containing your code so we can review the architecture and implementation before the next interview. By responding to the Tech Challenge intro email. 

---

## **5\. Evaluation Criteria**

We are grading you on the **“Demo Engineering Trifecta”**:

* **Aesthetic (40%):** Does it look like a $100M product, or an internal tool from 2010?  
* **Architecture (40%):** Did you successfully bridge the C\#, PowerShell, and Python components into a seamless flow?  
* **The Vibe (20%):** How effectively did you use AI tools to bypass the “boring” parts of coding to hit the 24-hour deadline?
