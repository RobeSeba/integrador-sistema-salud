/* SIBS - comportamiento del cliente.
   Sin librerias externas a proposito: el sistema debe funcionar sin CDN. */

(function () {
  "use strict";

  /* Enfoca el campo con error tras un envio fallido del login. */
  function enfocarError() {
    var error = document.querySelector(".mensaje-error");
    if (error) {
      var campo = document.querySelector("#usuario, #password");
      if (campo) { campo.focus(); }
    }
  }

  /* Al cambiar el rango de fechas se avisa si el inicio es posterior al fin. */
  function validarFechas() {
    var inicio = document.getElementById("fecha_inicio");
    var fin = document.getElementById("fecha_fin");
    if (!inicio || !fin || !inicio.value || !fin.value) { return true; }
    if (inicio.value > fin.value) {
      fin.setCustomValidity("La fecha final no puede ser anterior a la inicial.");
      fin.reportValidity();
      return false;
    }
    fin.setCustomValidity("");
    return true;
  }

  /* Filtros rapidos: ultimo mes de datos completo, anio completo, 90 dias. */
  function filtrosRapidos() {
    var inicio = document.getElementById("fecha_inicio");
    var fin = document.getElementById("fecha_fin");
    if (!inicio || !fin) { return; }

    var botones = document.querySelectorAll("[data-rango]");
    Array.prototype.forEach.call(botones, function (boton) {
      boton.addEventListener("click", function () {
        var rango = boton.getAttribute("data-rango");
        var hoy = new Date();
        var desde, hasta;

        if (rango === "anio") {
          desde = new Date(hoy.getFullYear() - 1, 0, 1);
          hasta = new Date(hoy.getFullYear() - 1, 11, 31);
        } else if (rango === "90d") {
          hasta = hoy;
          desde = new Date(hoy.getTime() - 90 * 86400000);
        } else {                       // "mes": el mes calendario anterior
          desde = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);
          hasta = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 31);
        }

        var iso = function (fecha) {
          return fecha.toISOString().slice(0, 10);
        };
        inicio.value = iso(desde);
        fin.value = iso(hasta);
        boton.form.submit();
      });
    });
  }

  /* Marca la fila de la tabla que recibe el foco del teclado. */
  function navegacionTabla() {
    var tablas = document.querySelectorAll(".tabla-datos tbody tr");
    Array.prototype.forEach.call(tablas, function (fila) {
      fila.addEventListener("mouseover", function () { fila.style.background = "#eef6fc"; });
      fila.addEventListener("mouseout", function () { fila.style.background = ""; });
    });
  }

  /* Evita el doble envio en formularios con carga de archivos o acciones
     destructivas (POST). */
  function evitarDobleEnvio() {
    var formularios = document.querySelectorAll("form");
    Array.prototype.forEach.call(formularios, function (formulario) {
      formulario.addEventListener("submit", function () {
        var boton = formulario.querySelector('button[type="submit"]');
        if (boton && !boton.dataset.confirmado) {
          boton.disabled = true;
          boton.dataset.confirmado = "1";
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    enfocarError();
    validarFechas();
    filtrosRapidos();
    navegacionTabla();
    evitarDobleEnvio();

    var inicio = document.getElementById("fecha_inicio");
    var fin = document.getElementById("fecha_fin");
    if (inicio) { inicio.addEventListener("change", validarFechas); }
    if (fin) { fin.addEventListener("change", validarFechas); }
  });
})();
