const loginForm = document.querySelector("#login-form");
const campusInput = document.querySelector("#campus-id");
const loginError = document.querySelector("#login-error");


loginForm.addEventListener("submit", function(event) {

    event.preventDefault();

    const campusID = campusInput.value.trim().toUpperCase();

    fetch("data/students_current.csv")
        .then(response => response.text())
        .then(data => {

            const studentExists = findStudent(data, campusID);

            if (studentExists) {

                // Save the ID so dashboard.html can access it
                sessionStorage.setItem("campusID", campusID);

                // Go to dashboard
                window.location.href = "dashboard.html";

            } else {

                loginError.textContent = "Campus ID not found.";

            }

        });

});


function findStudent(data, campusID) {

    const rows = data.trim().split("\n");

    // Start at 1 to skip the CSV header
    for (let i = 1; i < rows.length; i++) {

        const columns = rows[i].split(",");

        if (columns[0].trim() === campusID) {
            return true;
        }
    }

    return false;
}