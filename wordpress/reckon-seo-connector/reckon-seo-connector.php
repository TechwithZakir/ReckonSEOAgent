<?php
/**
 * Plugin Name: Reckon SEO Connector
 * Description: Stores and outputs the SEO title, meta description, canonical URL and JSON-LD schema that Reckon proposes, and exposes them to the WordPress REST API for approved, verifiable changes.
 * Version: 0.1.0
 * Requires at least: 6.0
 * Requires PHP: 7.4
 * License: GPL-2.0-or-later
 *
 * Design rules
 * - Writes happen only through the core REST API by a user who can edit the post
 *   (Application Password), never through a custom unauthenticated route.
 * - Every value is sanitized on write AND escaped on output.
 * - Nothing is output unless a value is set, so an inactive field leaves the theme untouched.
 * - No hidden text, cloaking or conditional output by visitor: every visitor and crawler
 *   receives the same markup.
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

const RECKON_SEO_FIELDS = array(
	'reckon_seo_title'       => 'sanitize_text_field',
	'reckon_seo_description' => 'sanitize_text_field',
	'reckon_seo_canonical'   => 'reckon_seo_sanitize_url',
	'reckon_seo_schema'      => 'reckon_seo_sanitize_schema',
);

/** Absolute http(s) URL only; anything else is stored as an empty string. */
function reckon_seo_sanitize_url( $value ) {
	$value = is_string( $value ) ? trim( $value ) : '';
	if ( '' === $value ) {
		return '';
	}
	$clean = esc_url_raw( $value, array( 'http', 'https' ) );
	return ( $clean && wp_parse_url( $clean, PHP_URL_HOST ) ) ? $clean : '';
}

/** JSON object or array only, re-encoded so the stored text is canonical and safe. */
function reckon_seo_sanitize_schema( $value ) {
	$value = is_string( $value ) ? trim( $value ) : '';
	if ( '' === $value || strlen( $value ) > 20000 ) {
		return '';
	}
	$decoded = json_decode( $value, true );
	if ( ! is_array( $decoded ) ) {
		return '';
	}
	$encoded = wp_json_encode( $decoded, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE );
	return is_string( $encoded ) ? $encoded : '';
}

add_action(
	'init',
	function () {
		foreach ( array( 'post', 'page' ) as $post_type ) {
			foreach ( RECKON_SEO_FIELDS as $key => $sanitizer ) {
				register_post_meta(
					$post_type,
					$key,
					array(
						'type'              => 'string',
						'single'            => true,
						'default'           => '',
						'show_in_rest'      => true,
						'sanitize_callback' => $sanitizer,
						'auth_callback'     => function ( $allowed, $meta_key, $post_id ) {
							return current_user_can( 'edit_post', (int) $post_id );
						},
					)
				);
			}
		}
	}
);

/** The current singular post's value for a field, or '' when unset. */
function reckon_seo_value( $key ) {
	if ( ! is_singular() ) {
		return '';
	}
	$value = get_post_meta( get_queried_object_id(), $key, true );
	return is_string( $value ) ? $value : '';
}

add_filter(
	'pre_get_document_title',
	function ( $title ) {
		$custom = reckon_seo_value( 'reckon_seo_title' );
		return '' !== $custom ? $custom : $title;
	},
	20
);

// Replace core's canonical link only when a canonical is set, so there is never a duplicate.
add_action(
	'wp',
	function () {
		if ( '' !== reckon_seo_value( 'reckon_seo_canonical' ) ) {
			remove_action( 'wp_head', 'rel_canonical' );
		}
	}
);

add_action(
	'wp_head',
	function () {
		$description = reckon_seo_value( 'reckon_seo_description' );
		if ( '' !== $description ) {
			printf( "<meta name=\"description\" content=\"%s\" />\n", esc_attr( $description ) );
		}

		$canonical = reckon_seo_value( 'reckon_seo_canonical' );
		if ( '' !== $canonical ) {
			printf( "<link rel=\"canonical\" href=\"%s\" />\n", esc_url( $canonical ) );
		}

		$schema = reckon_seo_value( 'reckon_seo_schema' );
		if ( '' !== $schema ) {
			$decoded = json_decode( $schema, true );
			if ( is_array( $decoded ) ) {
				// JSON_HEX_* keeps "</script>" and quotes from ever ending the script block.
				$safe = wp_json_encode(
					$decoded,
					JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT
				);
				if ( is_string( $safe ) ) {
					echo '<script type="application/ld+json">' . $safe . "</script>\n"; // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- JSON encoded with HEX flags above.
				}
			}
		}
	},
	1
);
